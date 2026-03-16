#!/usr/bin/python3

import argparse
import datetime
import json
import logging
import logging.handlers
import signal
import sys
import time
import traceback

import comwatt
import csscolors
import dateutil
import hue_color_converter
import pythonhuecontrol.v1.bridge
import suntime


class Monitor(object):

    def __init__(
            self, 
            comwatt_email=None, comwatt_password=None, 
            hue_bridge=None, hue_key=None, hue_light=None,
            headless=True):

        # Comwatt credentials
        self.comwatt_email = comwatt_email
        self.comwatt_password = comwatt_password

        # Philips Hue
        self.hue_bridge = hue_bridge
        self.hue_key = hue_key
        self.hue_light = hue_light

        # Location
        self.latitude = 0
        self.longitude = 0

        # Sun threshold
        self.threshold_sun = -1000000000

        # Browser options
        self.headless = headless

        # Thresolds and colors configuration
        self.thresholds = []

        # Internal objects
        self.bridge = None
        self.comwatt = None
        self.sun_tool = None
        self.light_monitor = None

        self.logger = logging.getLogger("Monitor")
        
        self.previous_state = -1000000000
        self.same_state_count = 0
        
        self.day = None
        self.sunrise = None
        self.sunset = None

    def initialize(self):

        # Initialize bridge connection
        self.bridge = pythonhuecontrol.v1.bridge.Bridge(self.hue_bridge, "http://" + self.hue_bridge + "/api/" + self.hue_key)

        # Find the specified light
        for light_id in self.bridge.light_ids:
            light = self.bridge.light(light_id)

            if light.name == self.hue_light:
                self.light_monitor = light
                break

        assert self.light_monitor is not None

        # Ready to go !
        self.do_run = True

    def load_configuration(self, config):

        self.comwatt_email = config["comwatt"]["email"]
        self.comwatt_password = config["comwatt"]["password"]

        self.hue_bridge = config["hue"]["bridge"]
        self.hue_key = config["hue"]["key"]
        self.hue_light = config["hue"]["light"]

        self.threshold_sun = config["thresholds"]["sun"]["min"]

        list_thresholds = [ v for v in config["thresholds"]["delta"] ]

        conv = hue_color_converter.Converter("C")

        for key in list_thresholds:
            value = config["thresholds"]["delta"][key]

            xyy = conv.hex_to_xyy(csscolors.__getattribute__(value.upper()).lstrip("#"))
            color = [xyy[0][0], xyy[0][1]]

            self.thresholds.append((int(key), color))

        self.sun_tool = suntime.Sun(config["location"]["latitude"], config["location"]["longitude"])


    def stop(self, signum, frame):
        self.logger.info("Stop")
        self.do_run = False


    def check_state(self, state):
         
        self.logger.debug("Check state: New=%d, Previous=%d" % (state, self.previous_state))

        if state == self.previous_state:
            self.same_state_count += 1
            if self.same_state_count >= 10:
                self.logger.info("Refreshing Commwatt")
                self.comwatt.refresh()
                self.same_state_count = 0
        else:
            self.previous_state = state
            self.same_state_count = 0

    def run(self, count=0, delay=5):

        self.logger.info("Run")

        signal.signal(signal.SIGTERM, self.stop)

        count = 0

        while self.do_run:
            
            self.logger.info(" Loop ".center(10, "="))

            loop = 0
            while self.do_run and loop < delay:
                time.sleep(1)
                loop += 1

            today = datetime.datetime.now()

            if not self.day or self.day != today.strftime("%d"):

                self.day = today.strftime("%d")
                self.sunrise = self.sun_tool.get_sunrise_time(today, dateutil.tz.gettz()).time()
                self.sunset = self.sun_tool.get_sunset_time(today, dateutil.tz.gettz()).time()

                self.logger.info("Day %s" % self.day)
                self.logger.info("Sunrise %s" % self.sunrise)
                self.logger.info("Sunset %s" % self.sunset)

            time_now = datetime.datetime.today().time()
            self.logger.info("Now %s" % time_now)

            if time_now < self.sunrise or time_now > self.sunset:
                self.logger.warning("Sun is not raised")
                self.comwatt = None
                continue

            if not self.comwatt:
                self.logger.debug("Connect to Comwatt")
                self.comwatt = comwatt.PowerGEN4(self.comwatt_email, self.comwatt_password, self.headless)

            try:
                list_sun = self.comwatt.get_devices("sun")
                device_sun = list_sun[0]

                if not device_sun.initialized:
                    self.logger.warning("Sun: Not initialized (count=%d)" % self.same_state_count)
                    self.check_state(-1000000000)
                    time.sleep(args.delay)
                    #time.sleep(10)
                    continue

                self.logger.info("Sun: %d" % device_sun.value_instant)

                if device_sun.value_instant < self.threshold_sun : 
                    # Sun is not sufficient -> Off
                    #TODO : Optimiser les appels API (mémoriser létat de la lampe)
                    self.light_monitor.switch_off()

                else:

                    list_injection = self.comwatt.get_devices("injection")
                    device_injection = list_injection[0]
                    list_withdrawal = self.comwatt.get_devices("withdrawal")
                    device_withdrawal = list_withdrawal[0] 

                    delta = device_injection.value_instant - device_withdrawal.value_instant

                    self.logger.info("Injection: %s" % device_injection.value_instant)
                    self.logger.info("Withdrawal: %s" % device_withdrawal.value_instant)
                    self.logger.info("Delta: %s" % delta)

                    self.check_state(delta)

                    if device_sun.value_instant < self.threshold_sun:
                        self.set("off")

                    else:
                        
                        color = None
                        i = 0
                        while i < len(self.thresholds):
                            if delta > self.thresholds[i][0]:
                                color = self.thresholds[i][1]
                            else:
                                break
                            i += 1

                        #TODO : Optimiser les appels API (mémoriser létat de la lampe)
                        self.light_monitor.switch_on()
                        self.light_monitor.state.set(xy=color)  

            except:
                self.comwatt.save_screenshot('/mnt/screenshot.png')
                traceback.print_exc()
                self.logger.fatal(traceback.format_exc)
                sys.exit(1)

            if args.count :

                count += 1

                if count >= args.count:
                    break


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--delay", type=int, default=1)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--log-file")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    args = parser.parse_args()
    
    if not args.log_level or args.log_level == "ERROR":
        log_level = logging.ERROR
    if args.log_level == "DEBUG":
        log_level = logging.DEBUG
    else:
        if args.log_level == "INFO":
            log_level = logging.INFO
        else:
            if args.log_level == "WARNING":
                log_level = logging.WARN

    if args.log_file:
        log_handler = logging.handlers.RotatingFileHandler(filename=args.log_file, mode="a", maxBytes=1024 * 1024, backupCount=5)
        logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=log_level, handlers=[log_handler])
    else:
        logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=log_level)


    fd = open(args.config)
    config = json.load(fd)
    fd.close()

    m = Monitor(headless=not args.show_browser)
    m.load_configuration(config)
    m.initialize()
    try:
        m.run(delay=args.delay)
    except:
        traceback.print_exc()
        logging.fatal(traceback.format_exc())
