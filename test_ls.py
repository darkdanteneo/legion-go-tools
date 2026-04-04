import evdev
for p in evdev.list_devices():
    d = evdev.InputDevice(p)
    if 'Legion' in d.name and d.info.vendor == 0x17EF:
        print(f'{d.name} ({p})')
        caps = d.capabilities()
        if evdev.ecodes.EV_ABS in caps:
            for code, ainfo in caps[evdev.ecodes.EV_ABS]:
                if code in [evdev.ecodes.ABS_Z, evdev.ecodes.ABS_RZ, evdev.ecodes.ABS_BRAKE, evdev.ecodes.ABS_GAS]:
                    print(f'  Trigger code={code}, max={ainfo.max}, min={ainfo.min}')