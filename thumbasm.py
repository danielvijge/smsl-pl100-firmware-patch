# Minimal two-pass Thumb assembler for the handful of encodings used by the patches.
# Each instruction is a tuple; labels are strings ending with ':'.
import struct

COND = {'eq': 0, 'ne': 1, 'hs': 2, 'lo': 3, 'mi': 4, 'pl': 5, 'hi': 8, 'ls': 9, 'ge': 10, 'lt': 11, 'gt': 12, 'le': 13}


def reg(r):
    return int(r[1:])


def enc_bl(pc, target, link=True):
    off = target - (pc + 4)
    assert -(1 << 24) <= off < (1 << 24) and off % 2 == 0, hex(off)
    s = (off >> 24) & 1
    i1 = (off >> 23) & 1
    i2 = (off >> 22) & 1
    imm10 = (off >> 12) & 0x3ff
    imm11 = (off >> 1) & 0x7ff
    j1 = (1 - i1) ^ s
    j2 = (1 - i2) ^ s
    h1 = 0xF000 | (s << 10) | imm10
    h2 = (0xD000 if link else 0x9000) | (j1 << 13) | (j2 << 11) | imm11
    return struct.pack('<HH', h1, h2)


def size(ins):
    op = ins[0]
    if op in ('bl', 'b.w', 'udiv'):
        return 4
    if op == 'word':
        return 4
    if op == 'bytes':
        return len(ins[1])
    if op == 'align':
        return None
    return 2


def assemble(prog, base):
    # pass 1: addresses
    labels = {}
    pc = base
    for ins in prog:
        if isinstance(ins, str):
            labels[ins.rstrip(':')] = pc
            continue
        if ins[0] == 'align':
            pc = (pc + 3) & ~3
            continue
        pc += size(ins)
    # pass 2: encode
    out = bytearray()
    pc = base

    def tgt(x):
        return labels[x] if isinstance(x, str) else x

    for ins in prog:
        if isinstance(ins, str):
            continue
        op, *a = ins
        if op == 'align':
            if pc % 4:
                out += b'\x00\xbf'  # nop
                pc += 2
            continue
        if op == 'bl':
            out += enc_bl(pc, tgt(a[0]))
        elif op == 'b.w':
            out += enc_bl(pc, tgt(a[0]), link=False)
        elif op == 'word':
            out += struct.pack('<I', tgt(a[0]))
        elif op == 'bytes':
            out += a[0]
        elif op == 'udiv':  # udiv rd, rn, rm
            out += struct.pack('<HH', 0xFBB0 | reg(a[1]), 0xF0F0 | reg(a[0]) << 8 | reg(a[2]))
        else:
            h = None
            if op == 'push':
                h = 0xB400 | a[0]
            elif op == 'pop':
                h = 0xBC00 | a[0]
            elif op == 'ldr_lit':  # ldr rt, label
                t = tgt(a[1])
                off = t - ((pc + 4) & ~3)
                assert 0 <= off < 1024 and off % 4 == 0, (ins, off)
                h = 0x4800 | reg(a[0]) << 8 | off >> 2
            elif op == 'ldr':  # ldr rt, [rn, #imm]
                assert a[2] % 4 == 0 and a[2] < 128
                h = 0x6800 | (a[2] >> 2) << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'ldrb':  # ldrb rt, [rn, #imm]
                assert a[2] < 32
                h = 0x7800 | a[2] << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'tst':
                h = 0x4200 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'bics':
                h = 0x4380 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'lsls':  # lsls rd, rm, #imm
                h = 0x0000 | a[2] << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'lsrs':  # lsrs rd, rm, #imm
                h = 0x0800 | a[2] << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'ands':  # ands rdn, rm
                h = 0x4000 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'muls':  # muls rdn, rm
                h = 0x4340 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'subs':  # subs rd, rn, rm
                h = 0x1A00 | reg(a[2]) << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'subs_i3':
                h = 0x1E00 | a[2] << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'str_sp':  # str rt, [sp, #imm]
                assert a[1] % 4 == 0 and a[1] < 1024
                h = 0x9000 | reg(a[0]) << 8 | a[1] >> 2
            elif op == 'ldr_sp':  # ldr rt, [sp, #imm]
                assert a[1] % 4 == 0 and a[1] < 1024
                h = 0x9800 | reg(a[0]) << 8 | a[1] >> 2
            elif op == 'orrs':  # orrs rdn, rm
                h = 0x4300 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'add_sp':  # add sp, #imm
                assert a[0] % 4 == 0 and a[0] < 512
                h = 0xB000 | a[0] >> 2
            elif op == 'sub_sp':  # sub sp, #imm
                assert a[0] % 4 == 0 and a[0] < 512
                h = 0xB080 | a[0] >> 2
            elif op == 'str':  # str rt, [rn, #imm]
                assert a[2] % 4 == 0 and a[2] < 128
                h = 0x6000 | (a[2] >> 2) << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'strb':  # strb rt, [rn, #imm]
                assert a[2] < 32
                h = 0x7000 | a[2] << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'movs':
                assert 0 <= a[1] < 256
                h = 0x2000 | reg(a[0]) << 8 | a[1]
            elif op == 'cmp':
                if isinstance(a[1], str):
                    h = 0x4280 | reg(a[1]) << 3 | reg(a[0])
                else:
                    h = 0x2800 | reg(a[0]) << 8 | a[1]
            elif op == 'adds_i8':
                h = 0x3000 | reg(a[0]) << 8 | a[1]
            elif op == 'adds_i3':
                h = 0x1C00 | a[2] << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'adds':
                h = 0x1800 | reg(a[2]) << 6 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'mov':
                h = 0x4600 | reg(a[1]) << 3 | reg(a[0])
            elif op == 'uxth':
                h = 0xB280 | reg(a[1]) << 3 | reg(a[0])
            elif op in ('cbz', 'cbnz'):
                off = tgt(a[1]) - (pc + 4)
                assert 0 <= off <= 126, (ins, off)
                h = (0xB100 if op == 'cbz' else 0xB900) | (off >> 6) << 9 | ((off >> 1) & 31) << 3 | reg(a[0])
            elif op == 'b':
                off = tgt(a[0]) - (pc + 4)
                assert -2048 <= off < 2048, (ins, off)
                h = 0xE000 | (off >> 1) & 0x7ff
            elif op.startswith('b') and op[1:] in COND:
                off = tgt(a[0]) - (pc + 4)
                assert -256 <= off < 256, (ins, off)
                h = 0xD000 | COND[op[1:]] << 8 | (off >> 1) & 0xff
            elif op == 'bx_lr':
                h = 0x4770
            elif op == 'nop':
                h = 0xBF00
            else:
                raise ValueError(op)
            out += struct.pack('<H', h)
        pc = base + len(out)
    return bytes(out), labels


def reglist(*regs, lr=False, pc=False):
    v = 0
    for r in regs:
        v |= 1 << reg(r)
    if lr or pc:
        v |= 0x100
    return v
