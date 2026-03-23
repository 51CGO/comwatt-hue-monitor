FROM python:3.13-slim-trixie

RUN python3 -m venv /comwatt_hue_monitor

RUN /comwatt_hue_monitor/bin/python3 -m pip install --upgrade pip
RUN /comwatt_hue_monitor/bin/python3 -m pip install rgbxy pythonhuecontrol comwatt-client sunshine-trigger>=1.0.5

VOLUME /mnt
WORKDIR /mnt

COPY monitor.py /comwatt_hue_monitor/bin/
RUN chmod +x /comwatt_hue_monitor/bin/monitor.py

ENV LOG_LEVEL="ERROR"

CMD /comwatt_hue_monitor/bin/python3 /comwatt_hue_monitor/bin/monitor.py --log-level $LOG_LEVEL /mnt/monitor.json
