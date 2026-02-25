from django.db import connection

cursor = connection.cursor()

# List of all missing columns per table
missing_columns = {
    "inventory_machine": [
        ("machine_image", "VARCHAR(100) DEFAULT ''"),
    ],
    "inventory_machinepart": [
        ("machine_id", "BIGINT REFERENCES inventory_machine(id) ON DELETE CASCADE"),
    ],
}

print("Adding all missing columns...\n")

for table_name, columns in missing_columns.items():
    for col_name, col_type in columns:
        try:
            sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type};"
            cursor.execute(sql)
            print(f"✓ Added {table_name}.{col_name}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"✓ {table_name}.{col_name} already exists")
            else:
                print(f"✗ Error on {table_name}.{col_name}: {str(e)[:100]}")

connection.commit()
print("\n✓ All missing columns added!")
