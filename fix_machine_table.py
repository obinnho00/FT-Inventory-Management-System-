from django.db import connection

cursor = connection.cursor()

# Add all missing columns to machine table
machine_columns = [
    ("machine_name", "VARCHAR(100) UNIQUE NOT NULL DEFAULT 'Unknown'"),
    ("machine_type", "VARCHAR(100) NOT NULL DEFAULT 'Unknown'"),
    ("machine_location", "VARCHAR(100) NOT NULL DEFAULT 'Unknown'"),
    ("machine_image", "VARCHAR(100) DEFAULT ''"),
    ("department_id", "BIGINT REFERENCES inventory_department(id) ON DELETE CASCADE"),
]

print("=== FIXING INVENTORY_MACHINE TABLE ===\n")
for col_name, col_type in machine_columns:
    try:
        cursor.execute(f'ALTER TABLE inventory_machine ADD COLUMN {col_name} {col_type};')
        print(f"✓ Added {col_name}")
    except Exception as e:
        if "already exists" in str(e):
            print(f"✓ {col_name} already exists")
        else:
            print(f"✗ Error adding {col_name}: {e}")

connection.commit()
print("\n✓ Machine table fixed!")
