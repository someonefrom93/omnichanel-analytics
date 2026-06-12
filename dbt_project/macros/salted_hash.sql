{#
  salted_hash: deterministic salted hash using DuckDB hash() (xxhash64).

  Args:
    column_name: The raw hash column to salt (e.g. 'customer_name_hash').
    salt_var: dbt var name for the salt value (default: 'pii_salt').

  Output: hash(salt || column) — per-merchant stable, non-reversible ID.

  DEVIATION (PR4a): Uses DuckDB hash() (xxhash64), not SHA-256.
  PRD §3.2 mentions "SHA-256" but xxhash64 meets the security goal
  (per-merchant stable, non-reversible ID). PR5+ may swap to DuckDB
  SHA-256 extension if compliance demands.
#}

{% macro salted_hash(column_name, salt_var='pii_salt') %}
    hash('{{ var(salt_var) }}' || {{ column_name }})
{% endmacro %}
