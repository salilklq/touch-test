import serial
import time
import struct
import sys
import serial.tools.list_ports

if sys.platform == "win32":
    import msvcrt
else:
    import select  # POSIX non-blocking input

_QUIT_INPUT_BUFFER = []

class ManipulatorHand:
    """机械手控制器（支持左手/右手，统一逻辑）"""
    # ==================== 官方协议寄存器地址映射（不可修改）====================
    # 位置控制寄存器 (0-5) - 固定顺序：大拇指翻转→大拇指弯曲→食指→中指→无名指→小拇指
    REG_ORDER = [
        0,    # 1.大拇指翻转 (f1)
        1,    # 2.大拇指弯曲 (f2)
        2,    # 3.食指弯曲   (f3)
        3,    # 4.中指弯曲   (f4)
        4,    # 5.无名指弯曲 (f5)
        5     # 6.小拇指弯曲 (f6)
    ]
    FINGER_NAMES = [
        "大拇指翻转(f1)",
        "大拇指弯曲(f2)",
        "食指弯曲(f3)",
        "中指弯曲(f4)",
        "无名指弯曲(f5)",
        "小拇指弯曲(f6)"
    ]

    # 速度控制寄存器 (6-11)
    SPEED_REG_ORDER = [6,7,8,9,10,11]
    # 力矩控制寄存器 (12-17)
    FORCE_REG_ORDER = [12,13,14,15,16,17]

    # 厂家专用寄存器（禁止操作）
    REG_MANU_START = 47
    REG_MANU_END = 57

    def __init__(self, port, hand_id, baud=115200):
        """
        初始化机械手
        :param port: 串口端口(如COM3)
        :param hand_id: 手ID（1=右手，2=左手）
        :param baud: 波特率(协议固定115200)
        """
        self.slave_id = hand_id  # 1=右手，2=左手
        self.baud = baud
        self.port = port
        self.ser = None
        self.hand_name = "右手" if hand_id == 1 else "左手"
        # 初始化串口并校验
        self._init_serial()

    def _init_serial(self):
        """串口初始化，带可用性校验"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=0.5,
                write_timeout=0.5
            )
            # 清空缓冲区
            self.ser.flushInput()
            self.ser.flushOutput()
            if self.ser.is_open:
                print(f"✅ {self.hand_name}(ID={self.slave_id})串口{self.port}初始化成功 | 波特率{self.baud}")
        except Exception as e:
            print(f"❌ {self.hand_name}(ID={self.slave_id})串口初始化失败：{e}")
            print("📌 可用串口列表：")
            for p in serial.tools.list_ports.comports():
                print(f"   - {p.device} | {p.description}")
            sys.exit(1)

    @staticmethod
    def _crc16_modbus(data):
        """Modbus-RTU标准CRC16校验（多项式0xA001）"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)

    def _write_06(self, reg_addr, value):
        """Modbus 06功能码：写单个寄存器（核心底层方法）"""
        # 1. 校验寄存器合法性
        if self.REG_MANU_START <= reg_addr <= self.REG_MANU_END:
            print(f"❌ {self.hand_name}禁止操作厂家寄存器：{reg_addr}")
            return False
        # 2. 校验数值范围（协议规定0-1000）
        if not (0 <= value <= 1000):
            print(f"❌ {self.hand_name}数值{value}超出协议范围[0,1000] | 寄存器{reg_addr}")
            return False
        # 3. 构建06功能码报文（大端打包）
        msg_body = struct.pack('>B B H H', self.slave_id, 0x06, reg_addr, value)
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc
        # 4. 发送报文（强制清空缓冲区）
        try:
            self.ser.flushInput()
            self.ser.flushOutput()
            self.ser.write(full_msg)
            time.sleep(0.05)  # 基础延时
            return True
        except Exception as e:
            print(f"❌ {self.hand_name}写寄存器{reg_addr}失败：{e}")
            return False

    def _write_10(self, reg_start, reg_count, values):
        """Modbus 10功能码（0x10）：写多个寄存器（单报文控制所有手指）"""
        # 1. 合法性校验
        if reg_count < 1 or reg_count > 123:
            print(f"❌ {self.hand_name}寄存器数量{reg_count}超出范围[1,123]")
            return False
        if len(values) != reg_count:
            print(f"❌ {self.hand_name}值数量({len(values)})与寄存器数量({reg_count})不匹配")
            return False
        for idx, val in enumerate(values):
            if not (0 <= val <= 1000):
                print(f"❌ {self.hand_name}第{idx+1}个值({val})超出范围[0,1000]")
                return False
        if self.REG_MANU_START <= reg_start <= self.REG_MANU_END:
            print(f"❌ {self.hand_name}禁止操作厂家寄存器：起始地址{reg_start}")
            return False

        # 2. 构建10功能码报文（大端打包）
        header = struct.pack('>B B H H', self.slave_id, 0x10, reg_start, reg_count)
        byte_count = reg_count * 2
        data_vals = b''
        for val in values:
            data_vals += struct.pack('>H', val)
        data_part = struct.pack('>B', byte_count) + data_vals
        msg_body = header + data_part
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc

        # 3. 发送单报文
        try:
            self.ser.flushInput()
            self.ser.flushOutput()
            self.ser.write(full_msg)
            # 打印报文（方便核对）
            hex_msg = ' '.join([f"{b:02X}" for b in full_msg])
            print(f"✅ {self.hand_name}10功能码单报文发送成功 | 报文：{hex_msg}")
            time.sleep(0.2)
            return True
        except Exception as e:
            print(f"❌ {self.hand_name}10功能码报文发送失败：{e}")
            return False

    def _read_03(self, reg_addr, reg_count=1):
        """Modbus 03功能码：读寄存器（核心底层方法）"""
        if reg_count < 1 or reg_count > 125:
            print(f"❌ {self.hand_name}读取数量{reg_count}超出范围[1,125]")
            return None
        # 构建03功能码报文
        msg_body = struct.pack('>B B H H', self.slave_id, 0x03, reg_addr, reg_count)
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc
        # 发送并读取响应
        try:
            self.ser.flushInput()
            self.ser.write(full_msg)
            time.sleep(0.1)
            resp = self.ser.read(self.ser.in_waiting or 10)
            # 解析响应
            if len(resp) < 5 or resp[1] != 0x03:
                print(f"❌ {self.hand_name}读寄存器{reg_addr}响应异常：{resp.hex() if resp else '无响应'}")
                return None
            # 解析数据（大端解包）
            byte_count = resp[2]
            values = []
            for i in range(0, byte_count, 2):
                val = struct.unpack('>H', resp[3+i:3+i+2])[0]
                values.append(val)
            return values
        except Exception as e:
            print(f"❌ {self.hand_name}读寄存器{reg_addr}失败：{e}")
            return None

    def set_speed(self, spd_val):
        """预设所有手指速度（协议0-1000），仅执行一次"""
        print(f"\n===== {self.hand_name}开始预设所有手指速度 [值：{spd_val}] =====")
        for idx, (reg, name) in enumerate(zip(self.SPEED_REG_ORDER, self.FINGER_NAMES)):
            name = f"{name}速度"
            if self._write_06(reg, spd_val):
                val = self._read_03(reg)
                if val and val[0] == spd_val:
                    print(f"✅ {self.hand_name}{name} | 地址{reg} | 写入{spd_val} | 验证成功")
                else:
                    print(f"⚠️ {self.hand_name}{name} | 地址{reg} | 写入{spd_val} | 验证失败(读取：{val})")
            else:
                print(f"❌ {self.hand_name}{name} | 地址{reg} | 写入失败")

    def set_force(self, for_val):
        """预设所有手指力矩（协议0-1000），仅执行一次"""
        print(f"\n===== {self.hand_name}开始预设所有手指力矩 [值：{for_val}] =====")
        for idx, (reg, name) in enumerate(zip(self.FORCE_REG_ORDER, self.FINGER_NAMES)):
            name = f"{name}力矩"
            if self._write_06(reg, for_val):
                val = self._read_03(reg)
                if val and val[0] == for_val:
                    print(f"✅ {self.hand_name}{name} | 地址{reg} | 写入{for_val} | 验证成功")
                else:
                    print(f"⚠️ {self.hand_name}{name} | 地址{reg} | 写入{for_val} | 验证失败(读取：{val})")
            else:
                print(f"❌ {self.hand_name}{name} | 地址{reg} | 写入失败")

    def execute_action(self, action_name, pos_list):
        """执行单段动作（10功能码单报文）"""
        print(f"\n📌 {self.hand_name}执行{action_name}")
        print(f"===== {self.hand_name}执行动作 | f1-f6值：{pos_list} =====")
        # 调用10功能码单报文（起始寄存器0，数量6）
        if self._write_10(reg_start=0, reg_count=6, values=pos_list):
            # 验证每个寄存器写入结果
            for reg, name, pos_val in zip(self.REG_ORDER, self.FINGER_NAMES, pos_list):
                val = self._read_03(reg)
                if val and val[0] == pos_val:
                    print(f"✅ {self.hand_name}{name} | 地址{reg} | 设为{pos_val} | 验证成功")
                else:
                    print(f"⚠️ {self.hand_name}{name} | 地址{reg} | 设为{pos_val} | 验证失败(读取：{val})")
        else:
            print(f"❌ {self.hand_name}{action_name}执行失败")
        print(f"===== {self.hand_name}{action_name}执行完成 =====\n")

    def reset_all_fingers(self):
        """退出时强制所有手指归零"""
        print(f"\n===== {self.hand_name}开始所有手指归零 =====")
        zero_list = [0] * 6
        # 10功能码单报文归零
        if self._write_10(reg_start=0, reg_count=6, values=zero_list):
            # 验证归零结果
            for reg, name in zip(self.REG_ORDER, self.FINGER_NAMES):
                val = self._read_03(reg)
                if val and val[0] == 0:
                    print(f"✅ {self.hand_name}{name} | 地址{reg} | 归零成功")
                else:
                    print(f"⚠️ {self.hand_name}{name} | 地址{reg} | 归零失败(当前值：{val})")
        else:
            print(f"❌ {self.hand_name}所有手指归零失败")
        print(f"===== {self.hand_name}所有手指归零完成 =====\n")

    def __del__(self):
        """析构函数，确保串口关闭"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"✅ {self.hand_name}串口已安全关闭")


def read_quit_command():
    """非阻塞检测退出指令。"""
    if sys.platform == "win32":
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ["\r", "\n"]:
                command = "".join(_QUIT_INPUT_BUFFER).strip().lower()
                _QUIT_INPUT_BUFFER.clear()
                return command if command in ["q", "quit"] else None
            if ch == "\003":
                raise KeyboardInterrupt
            if ch in ["\b", "\x7f"]:
                if _QUIT_INPUT_BUFFER:
                    _QUIT_INPUT_BUFFER.pop()
            else:
                _QUIT_INPUT_BUFFER.append(ch)
        return None

    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
        command = sys.stdin.readline().strip().lower()
        return command if command in ["q", "quit"] else None
    return None


# ==================== 多手多段动作循环测试核心逻辑 =====================
def multi_hand_action_loop_test():
    """
    多手多段动作循环测试：
    1. 配置控制模式（RIGHT_ONLY/LEFT_ONLY/BOTH_HANDS）
    2. 配置左右手的动作序列和串口
    3. 支持单独循环右手/左手，或同步循环两只手
    4. 输入q退出循环，自动归零
    """
    # ========== 【你只需修改这里的配置】 ==========
    # 控制模式选择：RIGHT_ONLY(仅右手) / LEFT_ONLY(仅左手) / BOTH_HANDS(两只手)
    CONTROL_MODE = "LEFT_ONLY"  # 可选值：RIGHT_ONLY / LEFT_ONLY / BOTH_HANDS
    
    # 串口配置
    RIGHT_HAND_PORT = "COM19"     # 右手串口
    LEFT_HAND_PORT = "COM19"      # 左手串口
    SPEED_VAL =1000              # 速度值（0-1000）
    FORCE_VAL =1000              # 力矩值（0-1000）
    
    # 右手动作序列：每个元素是(动作名称, [f1,f2,f3,f4,f5,f6], 执行后延时(秒))
    RIGHT_ACTION_SEQUENCE = [
        ("动作1：大拇指翻转500", [1000, 0, 0, 0, 0, 0], 0.5),
        ("动作2：大拇指弯曲500", [1000, 1000, 0, 0, 0, 0], 0.5),
        ("动作3：食指弯曲500", [0, 0, 0, 0, 0, 0], 0.5),
        ("动作4：全部归零", [0, 0, 1000, 1000, 1000, 1000], 1.0),
        ("动作4：全部归零", [0, 0, 0, 0, 0, 0], 1.0),
    ]
    
    # 左手动作序列：格式和右手一致（可独立配置不同动作）
    LEFT_ACTION_SEQUENCE = [
        ("动作1：大拇指翻转500", [1000, 0, 0, 0, 0, 0], 0.5),
        ("动作2：大拇指弯曲500", [1000, 1000, 0, 0, 0, 0], 0.5),
        ("动作3：食指弯曲500", [0, 0, 0, 0, 0, 0], 0.5),
        ("动作4：全部归零", [0, 0, 1000, 1000, 1000, 1000], 1.0),
        ("动作4：全部归零", [0, 0, 0, 0, 0, 0], 1.0),
    ]
    # ==============================================

    # 初始化机械手实例
    right_hand = None
    left_hand = None
    
    if CONTROL_MODE in ["RIGHT_ONLY", "BOTH_HANDS"]:
        right_hand = ManipulatorHand(RIGHT_HAND_PORT, hand_id=1)  # 右手ID=1
        right_hand.set_speed(SPEED_VAL)
        right_hand.set_force(FORCE_VAL)
    
    if CONTROL_MODE in ["LEFT_ONLY", "BOTH_HANDS"]:
        left_hand = ManipulatorHand(LEFT_HAND_PORT, hand_id=2)    # 左手ID=2
        left_hand.set_speed(SPEED_VAL)
        left_hand.set_force(FORCE_VAL)

    # 打印控制信息
    mode_desc = {
        "RIGHT_ONLY": "仅右手",
        "LEFT_ONLY": "仅左手",
        "BOTH_HANDS": "两只手同步"
    }
    print("\n===== 进入多手多段动作循环测试模式 =====")
    print(f"📌 控制模式：{mode_desc[CONTROL_MODE]}")
    print(f"📌 速度值：{SPEED_VAL} | 力矩值：{FORCE_VAL}")
    if right_hand:
        print(f"📌 右手配置：串口{RIGHT_HAND_PORT}(ID=1) | 动作序列{len(RIGHT_ACTION_SEQUENCE)}段")
    if left_hand:
        print(f"📌 左手配置：串口{LEFT_HAND_PORT}(ID=2) | 动作序列{len(LEFT_ACTION_SEQUENCE)}段")
    print("📌 操作说明：输入q并回车退出循环 | 按Ctrl+C也可退出")
    print("📌 开始循环执行动作序列...\n")

    try:
        loop_count = 0
        while True:
            loop_count += 1
            print(f"========== 第{loop_count}轮动作序列开始 ==========")
            
            # 按顺序执行每一段动作（确保左右手同步）
            max_action_count = max(len(RIGHT_ACTION_SEQUENCE) if right_hand else 0, 
                                   len(LEFT_ACTION_SEQUENCE) if left_hand else 0)
            
            for action_idx in range(max_action_count):
                # 检查是否有退出指令（非阻塞）
                if read_quit_command() in ["q", "quit"]:
                    print("\n⚠️  收到退出指令，停止循环")
                    raise KeyboardInterrupt  # 触发退出逻辑
                
                # 执行当前段动作
                current_delay = 0
                
                # 执行右手动作（如果有）
                if right_hand and action_idx < len(RIGHT_ACTION_SEQUENCE):
                    action_name, pos_list, delay = RIGHT_ACTION_SEQUENCE[action_idx]
                    right_hand.execute_action(action_name, pos_list)
                    current_delay = max(current_delay, delay)
                
                # 执行左手动作（如果有）
                if left_hand and action_idx < len(LEFT_ACTION_SEQUENCE):
                    action_name, pos_list, delay = LEFT_ACTION_SEQUENCE[action_idx]
                    left_hand.execute_action(action_name, pos_list)
                    current_delay = max(current_delay, delay)
                
                # 动作执行后延时（取两段动作的最大延时，确保同步）
                if current_delay > 0:
                    print(f"📌 本轮动作延时{current_delay*1000}ms...")
                    time.sleep(current_delay)
            
            print(f"========== 第{loop_count}轮动作序列完成 ==========\n")

    except KeyboardInterrupt:
        print("\n\n⚠️  捕获到退出指令，停止循环")
    finally:
        # 退出时归零并关闭串口
        if right_hand:
            right_hand.reset_all_fingers()
            del right_hand
        if left_hand:
            left_hand.reset_all_fingers()
            del left_hand

    print("===== 多手多段动作循环测试结束，程序正常退出 =====")

# ==================== 主程序入口 =====================
if __name__ == "__main__":
    # 直接运行多手多段动作循环测试
    multi_hand_action_loop_test()
