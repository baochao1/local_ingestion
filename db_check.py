import psycopg2

c = psycopg2.connect(host="localhost", port=5432, user="postgres",
                     password="postgres", dbname="local_ingestion", connect_timeout=5)
c.autocommit = True
cur = c.cursor()
cur.execute(
    "alter table notification_subscription "
    "add column if not exists datasource_id bigint"
)
cur.execute(
    "select column_name, data_type from information_schema.columns "
    "where table_name = %s order by ordinal_position",
    ("notification_subscription",),
)
for r in cur.fetchall():
    print(r)
c.close()
