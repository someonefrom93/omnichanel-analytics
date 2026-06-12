{#
  parse_bronze_filename: extracts target_date and run_timestamp_utc from a
  Bronze object filename.

  Input: a filename like 'orders-20260610T120000Z.json' or
         'reports_enqueue-20260610T120000Z.json'
  Output: a struct with two named fields:
    - target_date: date (e.g. DATE '2026-06-10')
    - run_timestamp_utc: timestamp (e.g. TIMESTAMP '2026-06-10 12:00:00')

  Filename format: {endpoint}-{YYYYMMDDTHHMMSSZ}.json
  The timestamp is the run_timestamp_utc (per SCN-014).
  The target_date is derived from the timestamp (the day of the run,
  which for backfill iterations equals the order date by convention).

  Uses DuckDB's regexp_extract (single-group-at-a-time) + STRUCT_PACK.
  This pattern is verified working in DuckDB 1.x.
#}

{% macro parse_bronze_filename(filename_column) %}
    STRUCT_PACK(
        target_date := CAST(
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})', 1) || '-' ||
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})', 2) || '-' ||
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})', 3) AS DATE
        ),
        run_timestamp_utc := CAST(
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z', 1) || '-' ||
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z', 2) || '-' ||
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z', 3) || ' ' ||
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z', 4) || ':' ||
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z', 5) || ':' ||
            regexp_extract({{ filename_column }}, '(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z', 6) || 'Z' AS TIMESTAMP
        )
    )
{% endmacro %}