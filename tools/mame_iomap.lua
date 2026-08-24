-- Which addresses outside RAM and ROM does a real Cybiko touch?
--
-- The on-chip peripherals are findable by reading the code: they are absolute
-- addresses in the instruction stream. Anything on the external bus is not --
-- it arrives in a register, so a static scan sees `mov.b @er2, r0l` and
-- nothing else. That is how the LCD at 0x600000 stayed invisible through an
-- entire sweep of the I/O registers.
--
-- So ask the machine. Tap reads and writes over everything, drop the two
-- regions that are memory, and print what is left with counts.
--
--   mame cybikov1 -video none -sound none -seconds_to_run N \
--        -autoboot_script tools/mame_iomap.lua
--
-- $CYIO_KEY, if set, is a key to hold down for the second half of the run --
-- the address whose read count jumps is the keyboard.

local SECS = tonumber(os.getenv("CYIO_SPLIT") or "0")

local cpu  = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]

-- ROM and SRAM. Everything else is a peripheral of some kind.
local function is_memory(a)
  return a < 0x008000 or (a >= 0x200000 and a < 0x280000)
end

local reads, writes = {}, {}

local function note(t, a)
  if is_memory(a) then return end
  t[a] = (t[a] or 0) + 1
end

local WIDTH = prog.data_width

_G.cy_io_rd = prog:install_read_tap(0x000000, 0xFFFFFF, "cy_io_rd",
  function(offset, data, mask)
    for shift = WIDTH - 8, 0, -8 do
      if ((mask >> shift) & 0xFF) ~= 0 then
        note(reads, offset + ((WIDTH - 8 - shift) // 8))
      end
    end
  end)

_G.cy_io_wr = prog:install_write_tap(0x000000, 0xFFFFFF, "cy_io_wr",
  function(offset, data, mask)
    for shift = WIDTH - 8, 0, -8 do
      if ((mask >> shift) & 0xFF) ~= 0 then
        note(writes, offset + ((WIDTH - 8 - shift) // 8))
      end
    end
  end)

_G.cy_io_stop = emu.add_machine_stop_notifier(function()
  local all = {}
  for a in pairs(reads) do all[a] = true end
  for a in pairs(writes) do all[a] = true end
  local keys = {}
  for a in pairs(all) do keys[#keys + 1] = a end
  table.sort(keys)
  print("[cyio] addr      reads    writes")
  for _, a in ipairs(keys) do
    print(string.format("[cyio] %06X %9d %9d",
                        a, reads[a] or 0, writes[a] or 0))
  end
  print(string.format("[cyio] %d addresses outside ROM and SRAM", #keys))
end)

print("[cyio] armed")
