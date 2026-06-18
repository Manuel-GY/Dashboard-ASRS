@echo off
start "Monitor CC01" python monitor_cc01.py
start "Monitor Robots" python monitor_robots.py
python serve.py
