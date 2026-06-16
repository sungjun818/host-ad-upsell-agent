"""DB 연결 및 월간 성과 리포트 쿼리."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pymysql
import pymysql.cursors

KST = timezone(timedelta(hours=9))


def connect() -> pymysql.Connection:
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT") or "3306"),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=60,
    )


def _month_range(months_ago: int) -> tuple[str, str]:
    """N개월 전의 첫날·마지막날 반환 (KST 기준)."""
    now = datetime.now(KST)
    # 이번달 1일에서 N번 이전 달로 이동
    target = now.replace(day=1)
    for _ in range(months_ago):
        target = (target - timedelta(days=1)).replace(day=1)
    last = (target.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return target.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d")


def get_report_month_label() -> str:
    """전월 레이블 반환 (예: '2025년 5월')."""
    start, _ = _month_range(1)
    dt = datetime.strptime(start, "%Y-%m-%d")
    return f"{dt.year}년 {dt.month}월"


def get_ad_hosts(conn, limit: int = 200) -> list[dict]:
    """스타터(15%) 이상 광고 중인 숙소의 전월/전전월 실적 조회."""
    this_start, this_end = _month_range(1)
    last_start, last_end = _month_range(2)

    sql = """
        SELECT
            acm.id                  AS acm_id,
            acm.name_expression     AS acm_name,
            aa.advert_name,
            aa.advert_commission,
            u.name                  AS host_name,
            u.email                 AS host_email,
            ui.phone_number         AS host_phone,
            SUBSTRING_INDEX(SUBSTRING_INDEX(acm.name_expression, '/', 1), '[', -1) AS region,
            -- 전월 실적
            COALESCE(COUNT(DISTINCT re1.id), 0) AS res_this_month,
            COALESCE(SUM(CASE WHEN re1.id IS NOT NULL THEN
                IF(re1.suggestion_price > 0, ROUND(re1.suggestion_price),
                   IF(re1.total_price_set = 0, ROUND(re1.total_price), ROUND(re1.total_price_set)))
            ELSE 0 END), 0) AS gmv_this_month,
            -- 전전월 실적
            COALESCE(COUNT(DISTINCT re2.id), 0) AS res_last_month,
            COALESCE(SUM(CASE WHEN re2.id IS NOT NULL THEN
                IF(re2.suggestion_price > 0, ROUND(re2.suggestion_price),
                   IF(re2.total_price_set = 0, ROUND(re2.total_price), ROUND(re2.total_price_set)))
            ELSE 0 END), 0) AS gmv_last_month
        FROM accommodations acm
        JOIN (
            SELECT aa1.accommodation_id, aa1.advert_name, aa1.advert_commission
            FROM accommodation_adverts aa1
            INNER JOIN (
                SELECT accommodation_id, MAX(success_at) AS max_success_at
                FROM accommodation_adverts
                WHERE success_at IS NOT NULL
                  AND (expiration_at IS NULL OR expiration_at > NOW())
                  AND advert_commission >= 0.15
                GROUP BY accommodation_id
            ) latest ON latest.accommodation_id = aa1.accommodation_id
                     AND latest.max_success_at = aa1.success_at
            WHERE aa1.success_at IS NOT NULL
              AND (aa1.expiration_at IS NULL OR aa1.expiration_at > NOW())
              AND aa1.advert_commission >= 0.15
        ) aa ON aa.accommodation_id = acm.id
        LEFT JOIN users u               ON u.id = acm.user_id
        LEFT JOIN user_infos ui         ON ui.user_id = u.id
        LEFT JOIN accommodation_types act ON act.id = acm.type_id
        LEFT JOIN rooms r               ON r.accommodation_id = acm.id
        LEFT JOIN reservations re1 ON re1.room_id = r.id
            AND re1.status IN (7, 8)
            AND DATE(re1.success_at) BETWEEN %s AND %s
        LEFT JOIN reservations re2 ON re2.room_id = r.id
            AND re2.status IN (7, 8)
            AND DATE(re2.success_at) BETWEEN %s AND %s
        WHERE acm.deleted_at IS NULL
          AND acm.is_test = 0
          AND u.email NOT LIKE '%%mrmention%%'
          AND u.email NOT LIKE '%%test%%'
          AND NOT (acm.name_expression LIKE '%%부산%%' AND acm.name_expression LIKE '%%워케이션%%')
          AND (act.name IS NULL OR act.name NOT LIKE '%%위탁')
        GROUP BY acm.id, acm.name_expression, aa.advert_name, aa.advert_commission,
                 u.name, u.email, ui.phone_number
        ORDER BY res_this_month DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (this_start, this_end, last_start, last_end, limit))
        return list(cur.fetchall())


def get_region_monthly_avg(conn, region: str) -> dict:
    """같은 지역 광고 숙소들의 전월 평균 예약 수 및 예약당 평균 GMV."""
    this_start, this_end = _month_range(1)
    sql = """
        SELECT
            COALESCE(AVG(sub.res_cnt), 0)                                        AS avg_res,
            COALESCE(AVG(CASE WHEN sub.res_cnt > 0
                THEN sub.gmv / sub.res_cnt ELSE NULL END), 0)                    AS avg_price_per_res,
            COUNT(*)                                                              AS ad_acm_cnt
        FROM (
            SELECT
                acm.id,
                COALESCE(COUNT(DISTINCT re.id), 0) AS res_cnt,
                COALESCE(SUM(IF(re.suggestion_price > 0, ROUND(re.suggestion_price),
                    IF(re.total_price_set = 0, ROUND(re.total_price),
                       ROUND(re.total_price_set)))), 0) AS gmv
            FROM accommodations acm
            JOIN (
                SELECT aa1.accommodation_id
                FROM accommodation_adverts aa1
                INNER JOIN (
                    SELECT accommodation_id, MAX(success_at) AS max_success_at
                    FROM accommodation_adverts
                    WHERE success_at IS NOT NULL
                      AND (expiration_at IS NULL OR expiration_at > NOW())
                      AND advert_commission >= 0.15
                    GROUP BY accommodation_id
                ) latest ON latest.accommodation_id = aa1.accommodation_id
                         AND latest.max_success_at = aa1.success_at
                WHERE aa1.success_at IS NOT NULL
                  AND (aa1.expiration_at IS NULL OR aa1.expiration_at > NOW())
                  AND aa1.advert_commission >= 0.15
                GROUP BY aa1.accommodation_id
            ) aa ON aa.accommodation_id = acm.id
            LEFT JOIN rooms r ON r.accommodation_id = acm.id
            LEFT JOIN reservations re ON re.room_id = r.id
                AND re.status IN (7, 8)
                AND DATE(re.success_at) BETWEEN %s AND %s
            WHERE acm.deleted_at IS NULL AND acm.is_test = 0
              AND acm.name_expression LIKE %s
            GROUP BY acm.id
        ) sub
    """
    with conn.cursor() as cur:
        cur.execute(sql, (this_start, this_end, f"%{region}%"))
        return cur.fetchone() or {"avg_res": 0, "avg_price_per_res": 0, "ad_acm_cnt": 0}
