import asyncio
from bleak import *
import logging
import time
import os
import argparse

# global variables for arguments:
gb_arg_filename = None
gb_arg_debug = False
gb_arg_log = None
gb_arg_simulation = False
# global variables for update process:
gb_bleak_client = None
gb_p8_address = None
gb_fee3_complete_len = 0
gb_fee3_complete_cmd = bytearray()
gb_fee3_received_len = 0
gb_fee3_notify_counter = 0
gb_state_watch_in_DFU_MODE = False
gb_state_update_finished = False
gb_received_update_crc16 = 0
gb_update_file_crc16 = None
gb_current_block_nb = -1
gb_update_file_data = bytearray()
gb_update_file_len = 0
gb_simulation_send_next = False
gb_disable_disconnect_handler = False

def debug_log(s):
    global gb_arg_debug
    global gb_arg_log
    global gb_log_file_handle
    if gb_arg_debug:
        print(s)
    if gb_arg_log:
        gb_log_file_handle.write(str(s)+'\n')
        gb_log_file_handle.flush()

# Print iterations progress from https://stackoverflow.com/questions/3173320/text-progress-bar-in-the-console
def printProgressBar (iteration, total, prefix = '', suffix = '', decimals = 1, length = 100, fill = '#', printEnd = "\r"):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    print('\r%s |%s| %s%% %s' % (prefix, bar, percent, suffix), end = printEnd)
    # Print New Line on Complete
    if iteration == total:
        print()

# This implementation is pretty slow...
def crc16(data : bytearray, offset, length):
    if data is None or offset < 0 or offset > len(data)- 1 and offset+length > len(data):
        return 0
    crc = 0xFEEA
    for i in range(0, length):
        crc ^= data[offset + i] << 8
        for j in range(0,8):
            if (crc & 0x8000) > 0:
                crc =(crc << 1) ^ 0x1021
            else:
                crc = crc << 1
    return crc & 0xFFFF

# This is fast:
def crc16_ccitt(crc: int, data: bytearray):
    msb = crc >> 8
    lsb = crc & 255
    for c in data:
        x = c ^ msb
        x ^= (x >> 4)
        msb = (lsb ^ (x >> 3) ^ (x << 4)) & 255
        lsb = (x ^ (x << 5)) & 255
    return (msb << 8) + lsb

def p8_crc16(data: bytearray):
    return crc16_ccitt(0xFEEA, data)

async def send_command(cmd: int, data: bytearray):
    global gb_bleak_client
    data2send = bytearray()
    data2send.append(0xFE)
    data2send.append(0xEA)
    data2send.append(0x10)
    data2send.append(len(data)+5)
    data2send.append(cmd)
    data2send.extend(data)
    debug_log(''.join('0x{:02x},'.format(x) for x in data2send))
    await gb_bleak_client.write_gatt_char("fee2", data2send)

async def read_gatt(uuid: str):
    global gb_bleak_client
    gatt = await gb_bleak_client.read_gatt_char(uuid)
    print("print gatt from notify:")
    print(gatt)

async def reconnect():
    global gb_p8_address
    global gb_bleak_client
    global gb_disable_disconnect_handler
    print("Device disconnected. Waiting 5 seconds to see if it automatically reconnects...")
    await asyncio.sleep(5)
    is_connected = await gb_bleak_client.is_connected()
    debug_log(f"Device connected?: {is_connected}")
    if is_connected:
        print("We're good, device reconnected automatically")
    else:
        print("disconnecting...")
        await gb_bleak_client.disconnect()
        while await gb_bleak_client.is_connected():
            await asyncio.sleep(1)
        print("disconnected")
        async with BleakClient(gb_p8_address, loop=asyncio.get_event_loop()) as client:
            print("Trying to force reconnnection and continue...")
            gb_bleak_client.set_disconnected_callback(dummy_disconnected_handler)
            gb_bleak_client = client
            gb_bleak_client.set_disconnected_callback(disconnected_handler)
            await gb_bleak_client.start_notify("fee3", callback=notification_handler_fee3)
            gb_disable_disconnect_handler = True

def disconnected_handler(client):
    global gb_disable_disconnect_handler
    if not(gb_disable_disconnect_handler):
        gb_disable_disconnect_handler = False
        asyncio.create_task(reconnect())

def dummy_disconnected_handler(client):
    pass

def notification_handler_fee3(sender, data: bytes):
    debug = True
    #"import" global variables
    global gb_fee3_complete_len
    global gb_fee3_complete_cmd
    global gb_fee3_received_len
    global gb_state_watch_in_DFU_MODE
    global gb_received_update_crc16
    global gb_update_file_crc16
    global gb_fee3_notify_counter
    global gb_disable_disconnect_handler
    global gb_state_update_finished

    gb_fee3_notify_counter += 1
    debug_log(f"Notify on 0xffe3 number #{gb_fee3_notify_counter}")

    ba = bytearray(data)
    # print(ba)
    # print(ba[:3])
    if ba[:3] == bytearray([0xFE, 0xEA, 0x10]):
        # receiving first part of the command
        gb_fee3_complete_len = ba[3]
        # print(gb_fee3_complete_len)
        gb_fee3_complete_cmd = ba
        gb_fee3_received_len = len(ba)
    elif gb_fee3_received_len < gb_fee3_complete_len:
        # receiving next part of the command
        gb_fee3_received_len += len(ba)
        gb_fee3_complete_cmd.extend(ba)
    
    if gb_fee3_received_len != gb_fee3_complete_len:
        # we're not finished receiving the command, wait for another part
        print("waiting to receive next part")
        return

    debug_log("received full command: ")
    debug_log(''.join('0x{:02x},'.format(x) for x in gb_fee3_complete_cmd))
    
    if (ba == bytearray([0xFE, 0xEA, 0x10, 0x07, 0x63, 0x0, 0x0])) and not(gb_state_watch_in_DFU_MODE):
        # update haven't stated yet (block number is 0)
        gb_state_watch_in_DFU_MODE = True
        print("Watch in DFU mode, starting update")
        asyncio.create_task(send_block(0))
    elif (ba[:5] == bytearray([0xFE, 0xEA, 0x10, 0x07, 0x63])) and gb_state_watch_in_DFU_MODE:
        # send block according to received number
        block_256_bytes_nb = int.from_bytes(ba[5:7], byteorder='big', signed=False)
        debug_log(f"Received request for block nb: {block_256_bytes_nb}")
        # print("Sending only first block this time, stopping now...")
        # return
        asyncio.create_task(send_block(block_256_bytes_nb))
    elif (ba[:7] == bytearray([0xFE, 0xEA, 0x10, 0x09, 0x63, 0xFF, 0xFF])) and gb_state_watch_in_DFU_MODE:
        # update is finished, we received CRC16
        gb_received_update_crc16 = int.from_bytes(ba[7:9], byteorder='big', signed=False)
        print(f"Received CRC from the watch: 0x{gb_received_update_crc16:x}")
        print(f"CRC16 from update file being: 0x{gb_update_file_crc16:x}")
        if gb_received_update_crc16 == gb_update_file_crc16:
            print("CRC16 match! Rebooting the watch")
            gb_disable_disconnect_handler = True
            asyncio.create_task(reboot(0))
            gb_state_update_finished = True
        else:
            print("Wrong CRC16!")
    else:
        gb_state_watch_in_DFU_MODE = True
        print("continuing aborted update...")

async def send_block(block_nb: int):
    global gb_current_block_nb
    global gb_update_file_data
    global gb_update_file_len
    if block_nb > gb_current_block_nb:
        if (gb_update_file_len - block_nb * 256) > 256:
            current_block = gb_update_file_data[block_nb*256:block_nb*256+256]
        else:
            current_block = gb_update_file_data[block_nb*256:]
    
    # print(f"Sending update block nb: {block_nb}/{int(gb_update_file_len/256)}")
    if gb_arg_debug:
        printProgressBar(block_nb, int(gb_update_file_len/256), suffix = f"(Sending update block nb: {block_nb}/{int(gb_update_file_len/256)})", length = 40, printEnd='\r\n')
        # you can do "tail -f current.txt" in another terminal to monitor progress without being flooded with debug messages
        with open("current.txt", "w") as f:
            f.write(f"Sending update block nb: {block_nb}/{int(gb_update_file_len/256)}"+'\n')
        debug_log(''.join('0x{:02x},'.format(x) for x in current_block))
    else:
        printProgressBar(block_nb, int(gb_update_file_len/256), suffix = f"(Sending update block nb: {block_nb}/{int(gb_update_file_len/256)})", length = 40)
    # create packet to be sent:
    packet = bytearray([0xFE]) # start byte
    current_block_crc16 = p8_crc16(current_block) # block nb
    debug_log(f"Calculated CRC16 for the block is 0x{current_block_crc16:04x}")
    packet.extend(bytearray(current_block_crc16.to_bytes(2, byteorder = 'big'))) # 2 bytes for crc16 of the block
    packet.extend(bytearray((len(current_block) & 0xFF).to_bytes(1, byteorder = 'big'))) # 1 byte for length of the block
    packet.extend(current_block) # actual data
    debug_log("Full packet is:")
    debug_log(''.join('0x{:02x},'.format(x) for x in packet))
    await send_packet(packet)

async def send_packet(data: bytearray):
    global gb_arg_simulation
    global gb_bleak_client
    global gb_simulation_send_next

    if len(data) > 20:
        part_nb = 0
        while (len(data) - part_nb * 20) > 20:
            packet_part = data[part_nb*20:part_nb*20+20]
            debug_log(f"Packet part {part_nb} is:")
            debug_log(''.join('0x{:02x},'.format(x) for x in packet_part))
            if not(gb_arg_simulation):
                await gb_bleak_client.write_gatt_char("fee5", packet_part)
            part_nb += 1
            # This delay is essential between each write
            # If you wait for too long, it won't work, and the watch will continue to ask fot the same block
            #       --> 300ms was tested working, but 400ms doesn't work
            # 1ms was tested functionnal on Macbook Pro 15 2019
            # 7.5ms is supposed to be the Android standard          --> total upload time: 136.4654278755188 seconds
            await asyncio.sleep(0.001)
        if (len(data) - part_nb * 20) > 0:
            packet_part = data[part_nb*20:]
            debug_log(f"Last packet part {part_nb} is:")
            debug_log(''.join('0x{:02x},'.format(x) for x in packet_part))
            if not(gb_arg_simulation):
                await gb_bleak_client.write_gatt_char("fee5", packet_part)
    else:
        debug_log("Packet part is:")
        debug_log(''.join('0x{:02x},'.format(x) for x in data))
        if not(gb_arg_simulation):
            await gb_bleak_client.write_gatt_char("fee5", data)
        print("small packet")
    if gb_arg_simulation:
        gb_simulation_send_next = True


async def reboot(filesize: int):
    global gb_arg_simulation
    global gb_bleak_client
    print(f"reboot with parameter filesize = {filesize}")
    if not(gb_arg_simulation):
        await send_command(0x63, filesize.to_bytes(4, byteorder = 'big'))


# simulate notify on fee3
async def test_update_simulated():
    global gb_arg_filename
    global gb_update_file_data
    global gb_update_file_len
    global gb_update_file_crc16
    global gb_simulation_send_next

    with open(gb_arg_filename, 'rb') as f:
        gb_update_file_data = bytearray(f.read())
        gb_update_file_len = len(gb_update_file_data)
        print(f"{gb_arg_filename} size: {gb_update_file_len}")
        debug_log(''.join('0x{:02x},'.format(x) for x in gb_update_file_len.to_bytes(4, byteorder = 'big')))
        
    crc = p8_crc16(gb_update_file_data)
    print(f"Calculated CRC16 is {crc} or 0x{crc:04x} in hex")

    gb_update_file_crc16 = crc
    notify = b'\xfe\xea\x10\x07\x63'
    blocks_nb = int(gb_update_file_len/256+1)
    for i in range(0,blocks_nb):
        gb_simulation_send_next = False
        notification_handler_fee3("fee3", notify + bytes([i >> 8, i & 0xFF]))
        while(not(gb_simulation_send_next)):
            await asyncio.sleep(0)
    notification_handler_fee3("fee3", b'\xfe\xea\x10\x09\x63\xFF\xFF' + gb_update_file_crc16.to_bytes(2, byteorder = 'big'))

def notification_handler(sender, data: bytes):
    print(f"{sender}: {data}")

async def run():
    global gb_arg_filename
    global gb_state_update_finished
    global gb_update_file_crc16
    global gb_bleak_client
    global gb_p8_address
    global gb_update_file_data
    global gb_update_file_len
    global gb_disable_disconnect_handler

    print("Searching for P8 watch...")
    # Check if the device is already connected
    services = ["FEEA"]
    devices = await get_connected_by_services(service_uuids=services)
    for d in devices:
        debug_log(d)
        if(d.name == "P8 a" or d.name == "P8a"):
            print("P8 is already connected, great!!")
            debug_log(d.__dict__)
            gb_p8_address = d.address
    # If not already connect, scan for it
    if not gb_p8_address:
        devices = await discover()
        for d in devices:
            debug_log(d)
            if(d.name == "P8 a" or d.name == "P8a"):
                print("P8 watch was found!!")
                debug_log(d.__dict__)
                gb_p8_address = d.address

        if(gb_p8_address == None):
            print("P8 wasn't found, sorry!")
            exit()

    async with BleakClient(gb_p8_address, loop=asyncio.get_event_loop()) as client:
        gb_bleak_client = client
        # gb_bleak_client.set_disconnected_callback(disconnected_handler)
        is_connected = await client.is_connected()
        debug_log(f"Device connected?: {is_connected}")

        if not(gb_update_file_crc16): # don't calculate again if already did before
            with open(gb_arg_filename, 'rb') as f:
                gb_update_file_data = bytearray(f.read())
                gb_update_file_len = len(gb_update_file_data)
                print(f"{gb_arg_filename} size: {gb_update_file_len}")
                debug_log(''.join('0x{:02x},'.format(x) for x in gb_update_file_len.to_bytes(4, byteorder = 'big')))

            crc = p8_crc16(gb_update_file_data)
            gb_update_file_crc16 = crc
            print(f"Calculated CRC16 is 0x{crc:04x}")
        
        gatt = await client.read_gatt_char("2a24")
        debug_log(gatt)
        # while await client.is_connected():
        #     await asyncio.sleep(0.5)
        # return
        gb_disable_disconnect_handler = True
        if(gatt == bytearray(b'DFU=0')):
            print("DFU=0. Rebooting into DFU_MODE...")
            await reboot(gb_update_file_len)
        else:
            print("DFU=1. We will continue the update process and hope that the previously given update size is right")
        
        print("disconnecting...")
        await client.disconnect()

        while await client.is_connected():
            await asyncio.sleep(0.5)

    if(gatt == bytearray(b'DFU=0')):
        print("Wait 7 seconds for the watch to reboot")
        await asyncio.sleep(7) #wait for the watch to reboot

    gb_disable_disconnect_handler = False
    async with BleakClient(gb_p8_address, loop=asyncio.get_event_loop()) as client:
        gb_bleak_client.set_disconnected_callback(dummy_disconnected_handler)
        gb_bleak_client = client
        # gb_bleak_client.set_disconnected_callback(disconnected_handler)
        is_connected = await client.is_connected()
        debug_log(f"Device connected?: {is_connected}")

        await client.start_notify("fee3", callback=notification_handler_fee3)

        gatt = await client.read_gatt_char("2a24")
        debug_log(gatt)
        if(gatt == bytearray(b'DFU=1')):
            print("DFU=1. We can continue!")
        else:
            print("Device not in DFU_MODE. Aborting...")
            print("disconnecting...")
            await client.disconnect()
            exit()

        # while not gb_state_update_finished:
        #     await asyncio.sleep(2)
        while await client.is_connected():
            await asyncio.sleep(0.5)

        print("Watch got disconnected...")
        await client.disconnect()

def main():
    global gb_arg_filename
    global gb_arg_debug
    global gb_arg_log
    global gb_arg_simulation
    global gb_state_update_finished
    global gb_log_file_handle
    parser = argparse.ArgumentParser(description='Update P8 watch over BLE')
    parser.add_argument('file', help='update file to be uploaded at 0x23000')
    parser.add_argument('--debug', '-d', action='store_true', help='print debug log')
    parser.add_argument('--log', '-l', help='save debug log to a file')
    parser.add_argument('--simulation', '-s', action='store_true', help="This will simulate every BLE packet \
        to be sent. It won't do any actual BLE action. This should be combined with --debug or --log.")

    args = parser.parse_args()
    gb_arg_filename = args.file
    gb_arg_debug = args.debug
    gb_arg_log = args.log
    gb_arg_simulation = args.simulation

    if gb_arg_debug:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    if not(gb_arg_log is None):
        gb_log_file_handle = open(gb_arg_log, "w+")
    loop = asyncio.get_event_loop()
    if gb_arg_simulation:
        loop.run_until_complete(test_update_simulated())
    else:
        while not gb_state_update_finished:
            loop.run_until_complete(run())
            time.sleep(2)

if __name__ == "__main__":
    start = time.time()
    main()
    end = time.time()
    print(f"Took {end - start} seconds to upload the update")

    



