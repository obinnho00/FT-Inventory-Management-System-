from django.db import connection

tables_sql = """
CREATE TABLE IF NOT EXISTS inventory_building (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_manufacturer (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(120) UNIQUE NOT NULL,
    phone VARCHAR(30) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_vendor (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(120) UNIQUE NOT NULL,
    phone VARCHAR(30) DEFAULT '',
    website VARCHAR(300) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_part (
    id BIGSERIAL PRIMARY KEY,
    model_number VARCHAR(100) NOT NULL,
    part_name VARCHAR(100) NOT NULL,
    description TEXT DEFAULT '',
    part_image VARCHAR(100) DEFAULT '',
    usage_description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_user_requirement (
    id BIGSERIAL PRIMARY KEY,
    requirement_description TEXT DEFAULT '',
    name_of_requester VARCHAR(100) DEFAULT '',
    date_reported TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    department_id BIGINT REFERENCES inventory_department(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory_machine (
    id BIGSERIAL PRIMARY KEY,
    machine_name VARCHAR(100) UNIQUE NOT NULL,
    machine_type VARCHAR(100) NOT NULL,
    machine_location VARCHAR(100) NOT NULL,
    machine_image VARCHAR(100) DEFAULT '',
    department_id BIGINT REFERENCES inventory_department(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory_machinepart (
    id BIGSERIAL PRIMARY KEY,
    quantity_left INTEGER DEFAULT 0,
    placement_location VARCHAR(200) DEFAULT '',
    compatibility_notes TEXT DEFAULT '',
    machine_id BIGINT NOT NULL REFERENCES inventory_machine(id) ON DELETE CASCADE,
    part_id BIGINT NOT NULL REFERENCES inventory_part(id) ON DELETE CASCADE,
    UNIQUE(machine_id, part_id)
);

CREATE TABLE IF NOT EXISTS inventory_machinesmaintenancetrackrecord (
    id BIGSERIAL PRIMARY KEY,
    issue_description TEXT DEFAULT '',
    date_reported TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    date_fixed TIMESTAMP NULL,
    time_to_fix INTERVAL NULL,
    part_consumed BOOLEAN DEFAULT FALSE,
    machine_id BIGINT NOT NULL REFERENCES inventory_machine(id) ON DELETE CASCADE,
    part_replaced_id BIGINT NULL REFERENCES inventory_part(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS inventory_useremails (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(254) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_vendorpart (
    id BIGSERIAL PRIMARY KEY,
    last_purchase_date TIMESTAMP NULL,
    part_id BIGINT NOT NULL REFERENCES inventory_part(id) ON DELETE CASCADE,
    vendor_id BIGINT NOT NULL REFERENCES inventory_vendor(id) ON DELETE CASCADE,
    manufacturer_id BIGINT NULL REFERENCES inventory_manufacturer(id) ON DELETE SET NULL,
    UNIQUE(part_id, vendor_id)
);
"""

cursor = connection.cursor()

for sql in tables_sql.split(';'):
    if sql.strip():
        try:
            cursor.execute(sql)
            print(f"✓ Executed: {sql.split()[5:7]}")
        except Exception as e:
            if "already exists" in str(e):
                print(f"✓ Table already exists")
            else:
                print(f"✗ Error: {e}")

connection.commit()
print("\n✓ All tables created successfully!")
