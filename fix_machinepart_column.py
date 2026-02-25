from django.db import connection

cursor = connection.cursor()

# Add missing part_id column to machinepart table
try:
    cursor.execute('''
        ALTER TABLE inventory_machinepart 
        ADD COLUMN part_id BIGINT REFERENCES inventory_part(id) ON DELETE CASCADE;
    ''')
    print("✓ Added part_id column to inventory_machinepart")
except Exception as e:
    if "already exists" in str(e):
        print("✓ Column part_id already exists")
    else:
        print(f"✗ Error: {e}")

connection.commit()
print("✓ Database fixed!")
