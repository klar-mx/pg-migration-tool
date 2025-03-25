#!/bin/bash

# Function to display usage
usage() {
    echo "Usage: $0 -s <SRC_DB_HOST> -t <TRG_DB_HOST> -P <DB_PORT> -d <DB_NAME> -U <SRC_DB_USER> -u <TRG_DB_USER> -S <SRC_DB_PASSWORD> -T <TRG_DB_PASSWORD>"
    exit 1
}

# Parse command-line arguments
while getopts ":s:t:P:d:U:u:S:T:" opt; do
    case "${opt}" in
        s)
            SRC_DB_HOST=${OPTARG}
            ;;
        t)
            TRG_DB_HOST=${OPTARG}
            ;;
        P)
            DB_PORT=${OPTARG}
            ;;
        d)
            DB_NAME=${OPTARG}
            ;;
        U)
            SRC_DB_USER=${OPTARG}
            ;;
        u)
            TRG_DB_USER=${OPTARG}
            ;;
        S)
            SRC_DB_PASSWORD=${OPTARG}
            ;;
        T)
            TRG_DB_PASSWORD=${OPTARG}
            ;;
        *)
            usage
            ;;
    esac
done

# Check if all required arguments are provided
if [ -z "${SRC_DB_HOST}" ] || [ -z "${TRG_DB_HOST}" ] || [ -z "${DB_PORT}" ] || [ -z "${DB_NAME}" ] || [ -z "${SRC_DB_USER}" ] || [ -z "${TRG_DB_USER}" ] || [ -z "${SRC_DB_PASSWORD}" ] || [ -z "${TRG_DB_PASSWORD}" ]; then
    usage
fi

# Export the passwords to be used by psql
export PGPASSWORD_SRC="${SRC_DB_PASSWORD}"
export PGPASSWORD_TRG="${TRG_DB_PASSWORD}"

# Get the list of tables in the source database
tables=$(PGPASSWORD="${PGPASSWORD_SRC}" psql -h "${SRC_DB_HOST}" -p "${DB_PORT}" -U "${SRC_DB_USER}" -d "${DB_NAME}" -t -c "SELECT tablename FROM pg_tables WHERE schemaname='public';")

# Print the header
printf "%-30s %-20s %-20s\n" "Table Name" "Row Count (Source)" "Row Count (Target)"
printf "%-30s %-20s %-20s\n" "----------" "-----------------" "-----------------"

# Iterate over each table and count the rows in source and target
for table in $tables; do
    table=$(echo $table | xargs) # Trim any leading or trailing whitespace
    # Check if the table exists in the source database
    table_exists_source=$(PGPASSWORD="${PGPASSWORD_SRC}" psql -h "${SRC_DB_HOST}" -p "${DB_PORT}" -U "${SRC_DB_USER}" -d "${DB_NAME}" -t -c "SELECT to_regclass('public.${table}');")
    # Check if the table exists in the target database
    table_exists_target=$(PGPASSWORD="${PGPASSWORD_TRG}" psql -h "${TRG_DB_HOST}" -p "${DB_PORT}" -U "${TRG_DB_USER}" -d "${DB_NAME}" -t -c "SELECT to_regclass('public.${table}');")

    if [[ $table_exists_source != " " && $table_exists_source != "" && $table_exists_target != " " && $table_exists_target != "" ]]; then
        row_count_source=$(PGPASSWORD="${PGPASSWORD_SRC}" psql -h "${SRC_DB_HOST}" -p "${DB_PORT}" -U "${SRC_DB_USER}" -d "${DB_NAME}" -t -c "SELECT COUNT(*) FROM \"$table\";")
        row_count_target=$(PGPASSWORD="${PGPASSWORD_TRG}" psql -h "${TRG_DB_HOST}" -p "${DB_PORT}" -U "${TRG_DB_USER}" -d "${DB_NAME}" -t -c "SELECT COUNT(*) FROM \"$table\";")
        printf "%-30s %-20s %-20s\n" "$table" "$row_count_source" "$row_count_target"
    elif [[ $table_exists_source != " " && $table_exists_source != "" ]]; then
        row_count_source=$(PGPASSWORD="${PGPASSWORD_SRC}" psql -h "${SRC_DB_HOST}" -p "${DB_PORT}" -U "${SRC_DB_USER}" -d "${DB_NAME}" -t -c "SELECT COUNT(*) FROM \"$table\";")
        printf "%-30s %-20s %-20s\n" "$table" "$row_count_source" "Table does not exist"
    elif [[ $table_exists_target != " " && $table_exists_target != "" ]]; then
        row_count_target=$(PGPASSWORD="${PGPASSWORD_TRG}" psql -h "${TRG_DB_HOST}" -p "${DB_PORT}" -U "${TRG_DB_USER}" -d "${DB_NAME}" -t -c "SELECT COUNT(*) FROM \"$table\";")
        printf "%-30s %-20s %-20s\n" "$table" "Table does not exist" "$row_count_target"
    else
        printf "%-30s %-20s %-20s\n" "$table" "Table does not exist" "Table does not exist"
    fi
done

