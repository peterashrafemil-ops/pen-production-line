# Ink Pen Production Line Simulation Report Outline

## 1. Introduction
This project implements a simulated ink pen manufacturing line. The selected product contains at least four components: ink cartridge, nib, barrel body, cap, and clip. The software simulates assembly, quality inspection, database logging, and dashboard visualization.

## 2. Production Line Concept
The line contains five stations: ink cartridge loading, nib press-fit, barrel closing, cap and clip mounting, and write-test inspection. Each pen passes through the stations sequentially and is accepted or rejected based on simulated quality logic.

## 3. Program Implementation
The backend is written in Python and stores machine states, product counters, temperature values, station progress, and defect reasons. The HMI is implemented with Tkinter using a dark industrial operator-console design. It includes START, STOP, RESET, and ACKNOWLEDGE FAULT controls.

## 4. InfluxDB and Grafana
InfluxDB stores production data in the bucket `pen_line`. Grafana reads the data using Flux queries and displays produced pens, defective pens, machine temperature, and machine state.

## 5. Tools Used
Python, Tkinter, Docker Desktop, Docker Compose, InfluxDB, Grafana, Visual Studio Code, GitHub, GitHub Pages, and ChatGPT were used.

## 6. Conclusion
The project demonstrates a complete software model of an ink pen production cell with HMI control, defect detection, database storage, and dashboard monitoring. Future work could include real sensors, PLC integration, SCADA, alarm history, OEE calculation, and predictive maintenance.

## Appendix A: AI Tool Use
ChatGPT was used to help create the project structure, code, troubleshooting steps, Grafana queries, documentation, and website text. The output was tested and corrected during implementation.
