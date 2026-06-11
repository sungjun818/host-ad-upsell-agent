"""DB 연결 및 업셀 타겟 분석 쿼리."""
from __future__ import annotations

import os
import pymysql
import pymysql.cursors


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


def get_no_ad_targets(conn, limit: int = 50) -> list[dict]:
    """광고 미가입 숙소 중 최근 90일 예약 실적 있는 숙소."""
    sql = """
        SELECT
            acm.id                  AS acm_id,
            acm.name_expression     AS acm_name,
            acm.sales_id,
            u.name                  AS host_name,
            u.email                 AS host_email,
            ui.phone_number         AS host_phone,
            COUNT(re.id)            AS res_90d,
            COALESCE(SUM(
                IF(re.suggestion_price, ROUND(re.suggestion_price),
                   IF(re.total_price_set = 0, ROUND(re.total_price),
                      ROUND(re.total_price_set)))
            ), 0)                   AS gmv_90d,
            SUBSTRING_INDEX(SUBSTRING_INDEX(acm.name_expression, '/', 1), '[', -1) AS region
        FROM accommodations acm
        LEFT JOIN users u         ON u.id = acm.user_id
        LEFT JOIN user_infos ui   ON ui.user_id = u.id
        LEFT JOIN rooms r         ON r.accommodation_id = acm.id
        LEFT JOIN reservations re ON re.room_id = r.id
            AND re.status IN (7, 8)
            AND re.success_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
        LEFT JOIN accommodation_adverts aa
            ON aa.accommodation_id = acm.id
            AND aa.success_at IS NOT NULL
            AND (aa.expiration_at IS NULL OR aa.expiration_at > NOW())
        WHERE acm.deleted_at IS NULL
          AND acm.is_test = 0
          AND aa.id IS NULL
          AND u.email NOT LIKE '%%mrmention%%'
          AND u.email NOT LIKE '%%test%%'
          AND NOT (acm.name_expression LIKE '%%부산%%' AND acm.name_expression LIKE '%%워케이션%%')
        GROUP BY acm.id, acm.name_expression, acm.sales_id,
                 u.name, u.email, ui.phone_number
        HAVING res_90d > 0
        ORDER BY res_90d DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def get_upgrade_targets(conn, limit: int = 20) -> list[dict]:
    """낮은 수수료(10-15%) 업그레이드 대상 숙소."""
    sql = """
        SELECT
            acm.id                  AS acm_id,
            acm.name_expression     AS acm_name,
            acm.sales_id,
            aa.advert_name,
            aa.advert_commission,
            u.name                  AS host_name,
            u.email                 AS host_email,
            ui.phone_number         AS host_phone,
            COUNT(re.id)            AS res_90d,
            COALESCE(SUM(
                IF(re.suggestion_price, ROUND(re.suggestion_price),
                   IF(re.total_price_set = 0, ROUND(re.total_price),
                      ROUND(re.total_price_set)))
            ), 0)                   AS gmv_90d,
            SUBSTRING_INDEX(SUBSTRING_INDEX(acm.name_expression, '/', 1), '[', -1) AS region
        FROM accommodations acm
        JOIN accommodation_adverts aa
            ON aa.accommodation_id = acm.id
            AND aa.success_at IS NOT NULL
            AND (aa.expiration_at IS NULL OR aa.expiration_at > NOW())
            AND aa.advert_commission <= 0.15
        LEFT JOIN users u         ON u.id = acm.user_id
        LEFT JOIN user_infos ui   ON ui.user_id = u.id
        LEFT JOIN rooms r         ON r.accommodation_id = acm.id
        LEFT JOIN reservations re ON re.room_id = r.id
            AND re.status IN (7, 8)
            AND re.success_at >= DATE_SUB(NOW(), INTERVAL 180 DAY)
        WHERE acm.deleted_at IS NULL AND acm.is_test = 0
          AND u.email NOT LIKE '%%mrmention%%'
          AND NOT (acm.name_expression LIKE '%%부산%%' AND acm.name_expression LIKE '%%워케이션%%')
        GROUP BY acm.id, acm.name_expression, acm.sales_id,
                 aa.advert_name, aa.advert_commission,
                 u.name, u.email, ui.phone_number
        ORDER BY res_90d DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def get_region_ad_avg(conn, region: str) -> dict:
    """같은 지역 광고 숙소들의 90일 평균 예약 수."""
    sql = """
        SELECT
            COALESCE(AVG(sub.res_90d), 0) AS avg_res,
            COUNT(*) AS ad_acm_cnt
        FROM (
            SELECT
                acm.id,
                COUNT(re.id) AS res_90d
            FROM accommodations acm
            JOIN accommodation_adverts aa
                ON aa.accommodation_id = acm.id
                AND aa.success_at IS NOT NULL
                AND (aa.expiration_at IS NULL OR aa.expiration_at > NOW())
            LEFT JOIN rooms r ON r.accommodation_id = acm.id
            LEFT JOIN reservations re ON re.room_id = r.id
                AND re.status IN (7, 8)
                AND re.success_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            WHERE acm.deleted_at IS NULL AND acm.is_test = 0
              AND acm.name_expression LIKE %s
            GROUP BY acm.id
        ) sub
    """
    with conn.cursor() as cur:
        cur.execute(sql, (f"%{region}%",))
        return cur.fetchone() or {"avg_res": 0, "ad_acm_cnt": 0}
