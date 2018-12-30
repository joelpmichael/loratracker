CREATE TABLE tracker_data (
    gw_id char(16) NOT NULL,
    gw_location geography(PointZ, 4326),
    app_id int NOT NULL,
    dev_eui char(16) NOT NULL,
    gw_rx_timestamp timestamptz NOT NULL,
    gw_rx_rssi int NOT NULL,
    gw_rx_snr float NOT NULL,
    gps_timestamp timestamptz NOT NULL,
    gps_location geography(PointZ, 4326)
);

CREATE INDEX idx_td_gateway_timestamp ON tracker_data (gw_id, gw_rx_timestamp);
CREATE INDEX idx_td_gps_timestamp ON tracker_data (gw_id, dev_eui, gps_timestamp);