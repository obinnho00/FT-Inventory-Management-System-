from django.db import connection

cursor = connection.cursor()

# Add all missing columns to machinepart table
columns_to_add = [
    ("placement_location", "VARCHAR(200) DEFAULT ''"),
    ("compatibility_notes", "TEXT DEFAULT ''"),
    ("quantity_left", "INTEGER DEFAULT 0"),
]

for col_name, col_type in columns_to_add:
    try:
        cursor.execute(f'''
            ALTER TABLE inventory_machinepart 
            ADD COLUMN {col_name} {col_type};
        ''')
        print(f"✓ Added column {col_name}")
    except Exception as e:
        if "already exists" in str(e):
            print(f"✓ Column {col_name} already exists")
        else:
            print(f"✗ Error adding {col_name}: {e}")

connection.commit()
print("\n✓ All missing columns added!")
