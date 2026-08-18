# Smoke-Detector-MAX30101
This repository holds a smoke detector software designed to be implemented on a MAX30101 sensor paired with an Arduino.

## Usage 

Before running the code, a [MAX30101 photosensor](https://learn.sparkfun.com/tutorials/sparkfun-photodetector-max30101-hookup-guide/introduction) must be linked to an Arduino board using an I2C connector. The Arduino must then be connected to a PC and loaded with the `Example1 Basic Readings` [sketch](https://learn.sparkfun.com/tutorials/sparkfun-photodetector-max30101-hookup-guide/arduino-examples). 

Once the physical sensors are ready, create a Python environment with the required packages. 

```bash
python -m venv .venv
source .venv/bin/activate
pip install streamlit altair pyyaml
```

Once the environment is activated, the smoke detector can be executed as follows:
```bash
python smoke_detector_monitor.py --config config.yaml
```

This will begin monitoring, saving the data for later viewing into a `smoke_detector.db` file. A separate log file will be created for each active channel. 

The config file is structured as follows: 
```yaml
arduino_port: "/dev/ttyACM0"
atlaspc_channel_map:
  0: 20 # channel 0 -> atlaspc20 
  2: 21 # channel 2 -> atlaspc21
  7: 22 # channel 7 -> atlaspc22
restart_time: 10 # hours
calculation_interval: 5 # minutes
```

Here are descriptions of each field:
- **arduino_port**: The USB port to which the Arduino board is connected
- **atlaspc_channel_map**: Mapping between the physical I2C channel, to which each smoke detector is connected, and the PC in which a given detector is placed. Strictly for labelling purposes. 
- **restart_time**: Time interval (in hours) after which the code is re-initialized. This was implemented to avoid a strange bug that occurs after 15 hours of running. Should remain unchanged. 
- **calculation_interval**: Time interval (in minutes) in which data is used to calculate / update the mean and standard deviation of the readings. 

Once `smoke_detector_monitor.py` is running, the dashboard can be opened, which should output a link to a `streamlit` webpage:
```bash
python dashboard.py
```

The webpage is interactive and should display live readings for each detector. 
