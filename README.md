# Victron dbus MQTT Mapper

This mapper takes a json message from the source MQTT broker and reformats the values to be published to Victron VenusOS device.

On the Venus device this message gets converted to a device using the dbus-mqtt-services script.

## Usage
The script can be executed using Python and Docker.

> Before you start, edit the ip addresses of the MQTT server and your Victron device and the source message topic in the file header.

### Start script using Python
1. Start the script using `python3 dbus_mapper.py`


### Start script using Docker
1. Ensure you have Docker installed: https://docs.docker.com/get-docker/
2. Build container using  `docker build -t victron-mqtt-mapper .`
3. Start container using  `docker run --name victron-mqtt-mapper -d victron-mqtt-mapper`

## Mapping
Mapping is done using the mapper.json file.
This file has the header in the device section:
```
{
    "device": {
        "service": "p1_grid_1",
        "serviceType": "grid",
        "serviceInstance": 0,
        "dbus_data": [
            {
                "path": "/Mgmt/ProcessName",
                "value": "P1 Bridge",
                "valueType": "string",
                "writeable": false
            },
            {
                "path": "/Mgmt/ProcessVersion",
                "value": "1.0",
                "valueType": "string",
                "writeable": false
            },
            {
                "path": "/Mgmt/Connection",
                "value": "MQTT P1",
                "valueType": "string",
                "writeable": false
            },
            {
                "path": "/ProductId",
                "value": "45069",
                "valueType": "integer",
                "writeable": false
            },
            {
                "path": "/ProductName",
                "value": "P1 Energy Meter",
                "valueType": "string",
                "writeable": false
            },
            {
                "path": "/FirmwareVersion",
                "value": "1.0",
                "valueType": "string",
                "writeable": false
            },
            {
                "path": "/HardwareVersion",
                "value": "1.0",
                "valueType": "string",
                "writeable": false
            },
            {
                "path": "/CustomName",
                "value": "P1 MQTT Mapper",
                "valueType": "string",
                "writeable": true
            }
```

as well as the fields to be mapped from the source message in the dbus_fields section.
This way, MQTT data from existing devices can easily be mapped to a Victron device.

```

    },
    "dbus_fields": [
        {
            "name": "PowerSumActual",
            "unit": "W",
            "valueType": "float",
            "description": "Actual electricity power imported - power exported in 1 Watt resolution",
            "path": "/Ac/Power"
        },
        {
            "name": "electricityImportedToday",
            "unit": "kWh",
            "valueType": "float",
            "description": "Actual electricity power delivered (+P) in 1 Watt resolution",
            "path": "/Ac/Energy/Forward",
            "multiplier": 0.001,
            "digits": 3
        },
    ]}
```


## Screenshot of result
![Tile Overview](examples/gridmeter_p1_homescreen.png)
![Remote Console - Overview](examples/gridmeter.png) 
![SmartMeter - Values](examples/gridmeter_p1.png)
![SmartMeter - Device Details](examples/gridmeter_p1_device.png)
