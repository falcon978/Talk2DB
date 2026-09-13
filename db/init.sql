-- Create readonly user
CREATE ROLE readonly_user WITH LOGIN PASSWORD 'readonly_pass';
ALTER ROLE readonly_user SET statement_timeout = '3000ms';

-- Create tables
CREATE TABLE farmer (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    district VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    registered_on DATE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE plot (
    id SERIAL PRIMARY KEY,
    farmer_id INTEGER REFERENCES farmer(id),
    area_hectares DECIMAL(10, 2) NOT NULL,
    soil_type VARCHAR(50) NOT NULL,
    district VARCHAR(100) NOT NULL,
    irrigation_type VARCHAR(50) NOT NULL
);

CREATE TABLE crop_cycle (
    id SERIAL PRIMARY KEY,
    plot_id INTEGER REFERENCES plot(id),
    crop VARCHAR(100) NOT NULL,
    season VARCHAR(50) NOT NULL, -- e.g., 'kharif', 'rabi', 'zaid'
    sown_date DATE NOT NULL,
    harvest_date DATE,
    expected_yield DECIMAL(10, 2),
    actual_yield DECIMAL(10, 2),
    status VARCHAR(50) NOT NULL -- ENUM: 'H' (Harvested), 'F' (Failed), 'P' (Planted), 'A' (Active)
);

CREATE TABLE sensor_reading (
    id SERIAL PRIMARY KEY,
    plot_id INTEGER REFERENCES plot(id),
    reading_type VARCHAR(50) NOT NULL, -- e.g., 'soil_moisture', 'temperature'
    value DECIMAL(10, 2) NOT NULL,
    recorded_at TIMESTAMP NOT NULL
);

CREATE TABLE advisory (
    id SERIAL PRIMARY KEY,
    plot_id INTEGER REFERENCES plot(id),
    issued_at TIMESTAMP NOT NULL,
    category VARCHAR(100) NOT NULL, -- e.g., 'pest', 'weather'
    severity VARCHAR(50) NOT NULL, -- e.g., 'low', 'medium', 'high'
    acknowledged_at TIMESTAMP
);

CREATE TABLE field_agent (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    district VARCHAR(100) NOT NULL,
    joined_on DATE NOT NULL
);

CREATE TABLE field_visit (
    id SERIAL PRIMARY KEY,
    plot_id INTEGER REFERENCES plot(id),
    agent_id INTEGER REFERENCES field_agent(id),
    visited_at TIMESTAMP NOT NULL,
    outcome VARCHAR(255) NOT NULL,
    notes TEXT
);

-- Grant privileges to readonly_user
GRANT CONNECT ON DATABASE agridb TO readonly_user;
GRANT USAGE ON SCHEMA public TO readonly_user;
GRANT SELECT ON farmer, plot, crop_cycle, sensor_reading, advisory, field_agent, field_visit TO readonly_user;

-- Create indexes for performance (especially sensor_reading which has ~2M rows)
-- Composite index for the most common query pattern (automatically covers plot_id alone, and plot_id + reading_type)
CREATE INDEX idx_sensor_composite ON sensor_reading(plot_id, reading_type, recorded_at);
-- Single-column indexes for queries that don't filter by plot_id
CREATE INDEX idx_sensor_type ON sensor_reading(reading_type);
CREATE INDEX idx_sensor_date ON sensor_reading(recorded_at);
CREATE INDEX idx_crop_cycle_plot_id ON crop_cycle(plot_id);
CREATE INDEX idx_crop_cycle_season ON crop_cycle(season);
CREATE INDEX idx_plot_farmer_id ON plot(farmer_id);
CREATE INDEX idx_plot_district ON plot(district);

-- Application tables (used by the App for audit logging, NOT queried by LLM)
CREATE TABLE chat_history (
    session_id VARCHAR(255) NOT NULL,
    turn_number INTEGER NOT NULL,
    user_query TEXT NOT NULL,
    operation VARCHAR(50),
    generated_sql TEXT,
    model_response TEXT,
    execution_status VARCHAR(50),
    retry_count INTEGER DEFAULT 0,
    latency_ms INTEGER,
    token_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, turn_number)
);
CREATE INDEX idx_chat_history_session ON chat_history(session_id);

CREATE TABLE system_errors (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255),
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add schema comments for units, ENUMs, and known data traps
COMMENT ON COLUMN plot.area_hectares IS 'Area in hectares (ha)';
COMMENT ON COLUMN crop_cycle.expected_yield IS 'Expected total yield for the plot in kg (not per hectare)';
COMMENT ON COLUMN crop_cycle.actual_yield IS 'Actual total yield for the plot in kg (not per hectare)';
COMMENT ON COLUMN crop_cycle.status IS 'ENUM: H=Harvested, F=Failed, P=Planted, A=Active';
COMMENT ON COLUMN sensor_reading.reading_type IS 'ENUM: soil_moisture, humidity, rainfall, temperature';
COMMENT ON COLUMN sensor_reading.value IS 'Sensor reading value. Exclude -273.0 (absolute zero error) and 999.9 (overflow error) in aggregations';
COMMENT ON COLUMN advisory.category IS 'ENUM: disease, harvest, weather, pest, nutrient, irrigation';
COMMENT ON COLUMN advisory.severity IS 'ENUM: info, warning, urgent, critical';
COMMENT ON COLUMN field_visit.outcome IS 'ENUM: completed, partial, rescheduled, farmer_absent, cancelled';

-- Seed data from CSV files
COPY farmer(id, name, district, state, registered_on, is_active) 
FROM '/docker-entrypoint-initdb.d/data/farmer.csv' DELIMITER ',' CSV HEADER;

COPY plot(id, farmer_id, area_hectares, soil_type, district, irrigation_type) 
FROM '/docker-entrypoint-initdb.d/data/plot.csv' DELIMITER ',' CSV HEADER;

COPY crop_cycle(id, plot_id, crop, season, sown_date, harvest_date, expected_yield, actual_yield, status) 
FROM '/docker-entrypoint-initdb.d/data/crop_cycle.csv' DELIMITER ',' CSV HEADER;

COPY sensor_reading(id, plot_id, reading_type, value, recorded_at) 
FROM '/docker-entrypoint-initdb.d/data/sensor_reading.csv' DELIMITER ',' CSV HEADER;

COPY advisory(id, plot_id, issued_at, category, severity, acknowledged_at) 
FROM '/docker-entrypoint-initdb.d/data/advisory.csv' DELIMITER ',' CSV HEADER;

COPY field_agent(id, name, district, joined_on) 
FROM '/docker-entrypoint-initdb.d/data/field_agent.csv' DELIMITER ',' CSV HEADER;

COPY field_visit(id, plot_id, agent_id, visited_at, outcome, notes) 
FROM '/docker-entrypoint-initdb.d/data/field_visit.csv' DELIMITER ',' CSV HEADER;

-- Update sequences so new inserts don't fail
SELECT setval('farmer_id_seq', (SELECT MAX(id) FROM farmer));
SELECT setval('plot_id_seq', (SELECT MAX(id) FROM plot));
SELECT setval('crop_cycle_id_seq', (SELECT MAX(id) FROM crop_cycle));
SELECT setval('sensor_reading_id_seq', (SELECT MAX(id) FROM sensor_reading));
SELECT setval('advisory_id_seq', (SELECT MAX(id) FROM advisory));
SELECT setval('field_agent_id_seq', (SELECT MAX(id) FROM field_agent));
SELECT setval('field_visit_id_seq', (SELECT MAX(id) FROM field_visit));
