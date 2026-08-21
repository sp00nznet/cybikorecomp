-- Find the CyOS decompressor by watching it work.
--
-- Reading the boot ROM for an unpacker did not find one, and 65% of that ROM
-- is behind indirect calls anyway. This takes the other route: run the real
-- thing under MAME and look for the routine that behaves like a decompressor.
--
-- The signature is specific. An unpacker writes a long *contiguous* run of
-- bytes to RAM and -- unlike a memcpy or a flash read -- it reads back from
-- inside what it has already written, because that is what a back-reference
-- is. So: group writes into runs, remember which PC made each, and count the
-- reads that land inside the region that PC is currently filling.
--
--   mame cybikov1 -video none -sound none -seconds_to_run N \
--        -autoboot_script tools/mame_probe.lua

local OUT     = os.getenv("CYPROBE_LOG") or "cyprobe.log"
local RAM_LO  = 0x200000          -- Cybiko Classic SRAM
local RAM_HI  = 0x23FFFF
local MIN_RUN = 64                -- shorter runs are not worth reporting

local cpu  = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local logf = io.open(OUT, "w")

local function pc()
  return cpu.state["PC"].value & 0xFFFFFF
end

local writers = {}      -- pc -> stats

local function writer(p)
  local w = writers[p]
  if not w then
    w = { writes = 0, best = 0, cur_start = -1, cur_end = -1,
          backrefs = 0, lo = nil, hi = nil }
    writers[p] = w
  end
  return w
end

logf:write("cybiko decompressor probe\n")
logf:write(string.format("watching writes to %06X-%06X\n\n", RAM_LO, RAM_HI))
logf:flush()

_G.cy_wtap = prog:install_write_tap(RAM_LO, RAM_HI, "cy_w",
  function(offset, data, mask)
    local w = writer(pc())
    w.writes = w.writes + 1
    if w.lo == nil or offset < w.lo then w.lo = offset end
    if w.hi == nil or offset > w.hi then w.hi = offset end
    if w.cur_end >= 0 and offset >= w.cur_end and offset <= w.cur_end + 4 then
      w.cur_end = offset
    else
      local len = w.cur_end - w.cur_start
      if len > w.best then w.best = len end
      w.cur_start, w.cur_end = offset, offset
    end
  end)

_G.cy_rtap = prog:install_read_tap(RAM_LO, RAM_HI, "cy_r",
  function(offset, data, mask)
    local w = writers[pc()]
    if w and w.cur_start >= 0 and w.lo and offset >= w.lo
       and offset <= w.cur_end then
      w.backrefs = w.backrefs + 1
    end
    return data
  end)

local function report(tag)
  local list, total = {}, 0
  for p, w in pairs(writers) do
    total = total + 1
    local len = w.cur_end - w.cur_start
    if len > w.best then w.best = len end
    if w.best >= MIN_RUN then list[#list + 1] = { p = p, w = w } end
  end
  table.sort(list, function(a, b) return a.w.best > b.w.best end)

  logf:write(string.format("--- %s: %d writing PCs, %d with runs >= %d ---\n",
                           tag, total, #list, MIN_RUN))
  logf:write(string.format("%-8s %9s %8s %9s  %s\n",
                           "pc", "writes", "bestrun", "backrefs", "range"))
  for i = 1, math.min(#list, 14) do
    local e = list[i]
    logf:write(string.format("%06X   %9d %8d %9d  %06X-%06X\n",
      e.p, e.w.writes, e.w.best, e.w.backrefs, e.w.lo or 0, e.w.hi or 0))
  end
  logf:write("\n")
  logf:flush()
end

local frames = 0
_G.cy_frame = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames % 120 == 0 then
    report(string.format("frame %d", frames))
  end
end)

_G.cy_stop = emu.add_machine_stop_notifier(function()
  report("final")
  logf:write("run ended\n")
  logf:close()
end)

print("[cyprobe] armed, logging to " .. OUT)
