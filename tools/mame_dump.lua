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

local OUT    = os.getenv("CYRAM_OUT") or "cyram.bin"
local RAM_LO = 0x200000
local RAM_HI = 0x23FFFF

local cpu  = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]

_G.cy_dump_stop = emu.add_machine_stop_notifier(function()
  local f = io.open(OUT, "wb")
  local chunk = {}
  for a = RAM_LO, RAM_HI do
    chunk[#chunk + 1] = string.char(prog:read_u8(a) & 0xFF)
    if #chunk == 4096 then
      f:write(table.concat(chunk))
      chunk = {}
    end
  end
  if #chunk > 0 then f:write(table.concat(chunk)) end
  f:close()
  print(string.format("[cydump] wrote %s (%d bytes)", OUT, RAM_HI - RAM_LO + 1))
end)

print("[cydump] armed")
