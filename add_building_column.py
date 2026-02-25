from django.db import connection

cursor = connection.cursor()

# Create Building table if it doesn't exist
try:
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventory_building (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(100) UNIQUE NOT NULL
    );''')
    print("✓ Building table ready")
except Exception as e:
    print(f"✗ Building table error: {e}")

# Add building_id column to Department if it doesn't exist  
try:
    cursor.execute('''ALTER TABLE inventory_department ADD COLUMN building_id BIGINT REFERENCES inventory_building(id) ON DELETE SET NULL;''')
    print("✓ Column building_id added to department")
except Exception as e:
    if "already exists" in str(e).lower():
        print("✓ Column building_id already exists")
    else:
        print(f"✗ Department column error: {e}")

connection.commit()
print("\n✓ Database schema updated successfully!")
