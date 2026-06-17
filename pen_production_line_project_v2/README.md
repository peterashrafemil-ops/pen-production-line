# Ink Pen Production Line Simulation

This is a complete Advanced Programming project for an **ink pen / marker production line**. It is a new concept with a different HMI layout from the previous pencil version.

## Production stages

1. Ink cartridge loading
2. Nib press-fit
3. Barrel closing
4. Cap and clip mount
5. Write-test inspection

## Main features

- Python backend production logic
- Dark industrial-style Tkinter HMI
- Start, Stop, Reset, and Acknowledge Fault controls
- Defect reasons displayed clearly on the HMI
- InfluxDB time-series database
- Grafana dashboard with production metrics
- Docker Compose setup for InfluxDB and Grafana
- GitHub Pages website file included as `index.html`

## Run commands

```powershell
docker compose down
docker compose up -d
py -3 -m pip install -r requirements.txt
py -3 app.py
```

## Grafana

Open:

```text
http://localhost:3000
```

Login:

```text
Username: admin
Password: admin
```

## InfluxDB settings

```text
URL: http://localhost:8086
Organization: srh
Bucket: pen_line
Token: pen-token
Measurement: pen_line
```

## Grafana fields

- produced_total
- good_total
- defective_total
- temperature_c
- state_value
- current_station_index
- current_product_id
