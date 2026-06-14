import serial
import time
import struct
import sys
import serial.tools.list_ports


class ManipulatorHand:
    """机械手控制器（支持左手/右手，统一逻辑）"""

    REG_ORDER = [0, 1, 2, 3, 4, 5]
    FINGER_NAMES = [
        "大拇指翻转(f1)",
        "大拇指弯曲(f2)",
        "食指弯曲(f3)",
        "中指弯曲(f4)",
        "无名指弯曲(f5)",
        "小拇指弯曲(f6)",
    ]
    SPEED_REG_ORDER = [6, 7, 8, 9, 10, 11]
    FORCE_REG_ORDER = [12, 13, 14, 15, 16, 17]
    REG_MANU_START = 47
    REG_MANU_END = 57

    DEFAULT_RETRIES = 3

    def __init__(self, port, hand_id, baud=115200, ser=None, hand_name=None):
        """
        :param port: 串口端口(如COM3)
        :param hand_id: 手ID/Modbus从机地址（1=右手，2=左手）
        :param baud: 波特率(协议固定115200)
        :param ser: 可选，已打开的serial.Serial实例（用于多手共享同一串口）
        :param hand_name: 可选，显示名称覆盖（默认按 hand_id 推断为右手/左手）
        """
        self.slave_id = hand_id
        self.baud = baud
        self.port = port
        if hand_name is not None:
            self.hand_name = hand_name
        else:
            self.hand_name = "右手" if hand_id == 1 else "左手"
        self._owns_serial = ser is None
        if ser is not None:
            self.ser = ser
            print(f"[OK] {self.hand_name}(ID={self.slave_id})复用已有串口{port}")
        else:
            self.ser = None
            self._init_serial()

    def _init_serial(self):
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=0.5,
                write_timeout=0.5,
            )
            self.ser.flushInput()
            self.ser.flushOutput()
            if self.ser.is_open:
                print(f"[OK] {self.hand_name}(ID={self.slave_id})串口{self.port}初始化成功 | 波特率{self.baud}")
        except Exception as e:
            print(f"[ERR] {self.hand_name}(ID={self.slave_id})串口初始化失败：{e}")
            print("[INFO] 可用串口列表：")
            for p in serial.tools.list_ports.comports():
                print(f"   - {p.device} | {p.description}")
            sys.exit(1)

    @staticmethod
    def _crc16_modbus(data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)

    def _retry(self, func, *args, retries=None):
        """通用重试包装器，失败时递增延时重试"""
        if retries is None:
            retries = self.DEFAULT_RETRIES
        last_result = None
        for attempt in range(retries):
            last_result = func(*args)
            if last_result is not None and last_result is not False:
                return last_result
            if attempt < retries - 1:
                delay = 0.1 * (attempt + 1)
                print(f"[WARN] {self.hand_name}第{attempt + 1}次尝试失败，{delay:.1f}s后重试...")
                time.sleep(delay)
        return last_result

    def _write_06_once(self, reg_addr, value):
        if self.REG_MANU_START <= reg_addr <= self.REG_MANU_END:
            print(f"[ERR] {self.hand_name}禁止操作厂家寄存器：{reg_addr}")
            return False
        if not (0 <= value <= 1000):
            print(f"[ERR] {self.hand_name}数值{value}超出协议范围[0,1000] | 寄存器{reg_addr}")
            return False
        msg_body = struct.pack('>B B H H', self.slave_id, 0x06, reg_addr, value)
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc
        try:
            self.ser.flushInput()
            self.ser.flushOutput()
            self.ser.write(full_msg)
            time.sleep(0.05)
            return True
        except Exception as e:
            print(f"[ERR] {self.hand_name}写寄存器{reg_addr}失败：{e}")
            return False

    def _write_06(self, reg_addr, value):
        return self._retry(self._write_06_once, reg_addr, value)

    def _write_10_once(self, reg_start, reg_count, values):
        if reg_count < 1 or reg_count > 123:
            print(f"[ERR] {self.hand_name}寄存器数量{reg_count}超出范围[1,123]")
            return False
        if len(values) != reg_count:
            print(f"[ERR] {self.hand_name}值数量({len(values)})与寄存器数量({reg_count})不匹配")
            return False
        for idx, val in enumerate(values):
            if not (0 <= val <= 1000):
                print(f"[ERR] {self.hand_name}第{idx+1}个值({val})超出范围[0,1000]")
                return False
        if self.REG_MANU_START <= reg_start <= self.REG_MANU_END:
            print(f"[ERR] {self.hand_name}禁止操作厂家寄存器：起始地址{reg_start}")
            return False

        header = struct.pack('>B B H H', self.slave_id, 0x10, reg_start, reg_count)
        byte_count = reg_count * 2
        data_vals = b''
        for val in values:
            data_vals += struct.pack('>H', val)
        data_part = struct.pack('>B', byte_count) + data_vals
        msg_body = header + data_part
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc

        try:
            self.ser.flushInput()
            self.ser.flushOutput()
            self.ser.write(full_msg)
            hex_msg = ' '.join([f"{b:02X}" for b in full_msg])
            print(f"[OK] {self.hand_name}10功能码单报文发送成功 | 报文：{hex_msg}")
            time.sleep(0.2)
            return True
        except Exception as e:
            print(f"[ERR] {self.hand_name}10功能码报文发送失败：{e}")
            return False

    def _write_10(self, reg_start, reg_count, values):
        return self._retry(self._write_10_once, reg_start, reg_count, values)

    def _read_03_once(self, reg_addr, reg_count=1):
        if reg_count < 1 or reg_count > 125:
            print(f"[ERR] {self.hand_name}读取数量{reg_count}超出范围[1,125]")
            return None
        msg_body = struct.pack('>B B H H', self.slave_id, 0x03, reg_addr, reg_count)
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc
        try:
            self.ser.flushInput()
            self.ser.write(full_msg)
            time.sleep(0.1)
            resp = self.ser.read(self.ser.in_waiting or 10)
            if len(resp) < 5 or resp[1] != 0x03:
                print(f"[ERR] {self.hand_name}读寄存器{reg_addr}响应异常：{resp.hex() if resp else '无响应'}")
                return None
            byte_count = resp[2]
            values = []
            for i in range(0, byte_count, 2):
                val = struct.unpack('>H', resp[3 + i:3 + i + 2])[0]
                values.append(val)
            return values
        except Exception as e:
            print(f"[ERR] {self.hand_name}读寄存器{reg_addr}失败：{e}")
            return None

    def _read_03(self, reg_addr, reg_count=1):
        return self._retry(self._read_03_once, reg_addr, reg_count)

    def set_speed(self, spd_val):
        print(f"\n===== {self.hand_name}开始预设所有手指速度 [值：{spd_val}] =====")
        for reg, name in zip(self.SPEED_REG_ORDER, self.FINGER_NAMES):
            label = f"{name}速度"
            if self._write_06(reg, spd_val):
                val = self._read_03(reg)
                if val and val[0] == spd_val:
                    print(f"[OK] {self.hand_name}{label} | 地址{reg} | 写入{spd_val} | 验证成功")
                else:
                    print(f"[WARN] {self.hand_name}{label} | 地址{reg} | 写入{spd_val} | 验证失败(读取：{val})")
            else:
                print(f"[ERR] {self.hand_name}{label} | 地址{reg} | 写入失败")

    def set_force(self, for_val):
        print(f"\n===== {self.hand_name}开始预设所有手指力矩 [值：{for_val}] =====")
        for reg, name in zip(self.FORCE_REG_ORDER, self.FINGER_NAMES):
            label = f"{name}力矩"
            if self._write_06(reg, for_val):
                val = self._read_03(reg)
                if val and val[0] == for_val:
                    print(f"[OK] {self.hand_name}{label} | 地址{reg} | 写入{for_val} | 验证成功")
                else:
                    print(f"[WARN] {self.hand_name}{label} | 地址{reg} | 写入{for_val} | 验证失败(读取：{val})")
            else:
                print(f"[ERR] {self.hand_name}{label} | 地址{reg} | 写入失败")

    def execute_action(self, action_name, pos_list):
        print(f"\n[INFO] {self.hand_name}执行{action_name}")
        print(f"===== {self.hand_name}执行动作 | f1-f6值：{pos_list} =====")
        if self._write_10(reg_start=0, reg_count=6, values=pos_list):
            for reg, name, pos_val in zip(self.REG_ORDER, self.FINGER_NAMES, pos_list):
                val = self._read_03(reg)
                if val and val[0] == pos_val:
                    print(f"[OK] {self.hand_name}{name} | 地址{reg} | 设为{pos_val} | 验证成功")
                else:
                    print(f"[WARN] {self.hand_name}{name} | 地址{reg} | 设为{pos_val} | 验证失败(读取：{val})")
        else:
            print(f"[ERR] {self.hand_name}{action_name}执行失败")
        print(f"===== {self.hand_name}{action_name}执行完成 =====\n")

    def set_all_fingers_position(self, pos_list):
        print(f"\n===== {self.hand_name}开始批量设置所有手指位置 | 输入值：{pos_list} =====")
        if self._write_10(reg_start=0, reg_count=6, values=pos_list):
            for reg, name, pos_val in zip(self.REG_ORDER, self.FINGER_NAMES, pos_list):
                val = self._read_03(reg)
                if val and val[0] == pos_val:
                    print(f"[OK] {self.hand_name}{name} | 地址{reg} | 设为{pos_val} | 验证成功")
                else:
                    print(f"[WARN] {self.hand_name}{name} | 地址{reg} | 设为{pos_val} | 验证失败(读取：{val})")
        else:
            print(f"[ERR] {self.hand_name}所有手指位置设置失败")
        print(f"===== {self.hand_name}所有手指位置设置完成 =====\n")
        time.sleep(0.2)

    def reset_all_fingers(self):
        print(f"\n===== {self.hand_name}开始所有手指归零 =====")
        zero_list = [0] * 6
        if self._write_10(reg_start=0, reg_count=6, values=zero_list):
            for reg, name in zip(self.REG_ORDER, self.FINGER_NAMES):
                val = self._read_03(reg)
                if val and val[0] == 0:
                    print(f"[OK] {self.hand_name}{name} | 地址{reg} | 归零成功")
                else:
                    print(f"[WARN] {self.hand_name}{name} | 地址{reg} | 归零失败(当前值：{val})")
        else:
            print(f"[ERR] {self.hand_name}所有手指归零失败")
        print(f"===== {self.hand_name}所有手指归零完成 =====\n")

    def close(self):
        if self._owns_serial and self.ser and self.ser.is_open:
            self.ser.close()
            print(f"[OK] {self.hand_name}串口已安全关闭")

    def __del__(self):
        self.close()
