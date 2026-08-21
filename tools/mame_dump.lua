-- Dump Cybiko RAM after boot, so it can be compared against the flash.
--
-- The question this answers: does CyOS arrive in RAM byte-for-byte from the
-- flash, or transformed? If a region of RAM cannot be found verbatim in the
-- flash image, it was unpacked on the way -- and that region is a plaintext
-- to match against its packed source, which is worth far more than any amount
-- of staring at the unpacker.
--
--   mame cybikov1 -video none -sound none -seconds_to_run N \
--        -autoboot_script tools/mame_dump.lua
--
-- Writes cyram.bin (256 KB, the whole SRAM).

local OUT     = os.getenv("CYRAM_OUT") or "cyram.bin"
local OUT_IO  = os.getenv("CYIO_OUT")  or "cyio.bin"
local RAM_LO  = 0x200000
local RAM_HI  = 0x23FFFF
-- On-chip RAM and the I/O block. The boot ROM keeps its API dispatch table
-- here -- 43 of its indirect calls load a target from a fixed address in this
-- range, so without it those calls cannot be resolved at all.
local IO_LO   = 0xFFE000
local IO_HI   = 0xFFFFFF

local cpu  = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]

local function dump(path, lo, hi)
  local f = io.open(path, "wb")
  local chunk = {}
  for a = lo, hi do
    chunk[#chunk + 1] = string.char(prog:read_u8(a) & 0xFF)
    if #chunk == 4096 then
      f:write(table.concat(chunk))
      chunk = {}
    end
  end
  if #chunk > 0 then f:write(table.concat(chunk)) end
  f:close()
  print(string.format("[cydump] wrote %s (%d bytes)", path, hi - lo + 1))
end

_G.cy_dump_stop = emu.add_machine_stop_notifier(function()
  dump(OUT, RAM_LO, RAM_HI)
  dump(OUT_IO, IO_LO, IO_HI)
end)

print("[cydump] armed")
