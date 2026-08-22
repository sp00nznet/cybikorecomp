-- Record MAME's per-instruction state, to diff the recompiled core against.
--
-- The recompiled boot ROM runs 2819 dispatches from reset and then transfers
-- to address zero. Somewhere before that it computed something different from
-- the hardware, and no amount of staring at 39,000 instructions will say
-- where. Running a known-good implementation beside ours and comparing every
-- instruction says exactly where, which is how the Tamagotchi's RST F,i bug
-- was found.
--
-- Instruction fetches go through read taps, so a read whose address equals the
-- PC is the start of an instruction. Recording state there gives the machine
-- state *before* each instruction executes.
--
--   mame cybikov1 -video none -sound none -seconds_to_run N \
--        -autoboot_script tools/mame_difftrace.lua
--
-- Writes cytrace.bin: 40 bytes per instruction, big-endian --
-- pc(4) er0..er7(32) ccr(4).

local OUT   = os.getenv("CYTRACE_OUT") or "cytrace.bin"
local LIMIT = tonumber(os.getenv("CYTRACE_N") or "200000")

local cpu  = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local st   = cpu.state

local f = io.open(OUT, "wb")
local n = 0
local buf = {}

local function be32(v)
  v = v & 0xFFFFFFFF
  return string.char((v >> 24) & 0xFF, (v >> 16) & 0xFF,
                     (v >> 8) & 0xFF, v & 0xFF)
end

-- The boot ROM only; CyOS lives in RAM and MAME does not appear to route
-- those fetches through taps.
_G.cy_dt_tap = prog:install_read_tap(0x000000, 0x007FFF, "cy_dt",
  function(offset, data, mask)
    if n >= LIMIT then return data end
    local pc = st["PC"].value & 0xFFFFFF
    if offset ~= pc then return data end

    n = n + 1
    buf[#buf + 1] = be32(pc)
    for i = 0, 7 do
      buf[#buf + 1] = be32(st["ER" .. i].value)
    end
    buf[#buf + 1] = be32(st["CCR"].value)

    if #buf >= 4000 then
      f:write(table.concat(buf))
      buf = {}
    end
    return data
  end)

_G.cy_dt_stop = emu.add_machine_stop_notifier(function()
  if #buf > 0 then f:write(table.concat(buf)) end
  f:close()
  print(string.format("[cytrace] wrote %s: %d instructions", OUT, n))
end)

print("[cytrace] armed, limit " .. LIMIT)
