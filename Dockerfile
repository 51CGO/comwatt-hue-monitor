FROM python:3.11-slim-bookworm

RUN python3 -m venv /comwatt_hue_monitor

RUN /comwatt_hue_monitor/bin/python3 -m pip install --upgrade pip
RUN /comwatt_hue_monitor/bin/python3 -m pip install rgbxy pythonhuecontrol comwatt-client

VOLUME /mnt
WORKDIR /mnt

COPY monitor.py /comwatt_hue_monitor/bin/
RUN chmod +x /comwatt_hue_monitor/bin/monitor.py

ENV LOG_LEVEL="ERROR"

CMD /comwatt_hue_monitor/bin/python3 /comwatt_hue_monitor/bin/monitor.py --log-level $LOG_LEVEL /mnt/monitor.json
