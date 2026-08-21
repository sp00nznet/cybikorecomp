-- Record every address the Cybiko actually executes.
--
-- Static tracing finds code by following transfers whose target is a constant.
-- On a register machine running C++ that misses a lot: the recompiled boot ROM
-- gets four instructions into init and then wants 0x00204C, which is perfectly
-- real code that nothing jumps to statically.
--
-- So take the ground truth. Tap reads over the code regions and keep the ones
-- whose address equals the PC -- those are instruction fetches, and everything
-- else is the program reading its own data.
--
--   mame cybikov1 -video none -sound none -seconds_to_run N \
--        -autoboot_script tools/mame_pctrace.lua
--
-- Writes cypc.txt, one hex address per line, which analyze.py takes as seeds.

local OUT = os.getenv("CYPC_OUT") or "cypc.txt"

local REGIONS = {
  { 0x000000, 0x007FFF },   -- boot ROM
  { 0x200000, 0x23FFFF },   -- SRAM, where CyOS runs
}

local cpu  = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]

local seen = {}
local nseen = 0
local nfetch = 0
local ndata = 0

_G.cy_pc_taps = {}
for i, r in ipairs(REGIONS) do
  _G.cy_pc_taps[i] = prog:install_read_tap(r[1], r[2], "cy_pc",
    function(offset, data, mask)
      -- An instruction fetch reads from where the PC is. Anything else is
      -- the program looking at its own data, and seeding on that would put
      -- the decoder into tables and strings.
      if offset == (cpu.state["PC"].value & 0xFFFFFF) then
        nfetch = nfetch + 1
        if not seen[offset] then
          seen[offset] = true
          nseen = nseen + 1
        end
      else
        ndata = ndata + 1
      end
      return data
    end)
end

local frames = 0
_G.cy_pc_frame = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames % 300 == 0 then
    print(string.format("[cypc] frame %d  distinct=%d fetches=%d data=%d",
                        frames, nseen, nfetch, ndata))
  end
end)

_G.cy_pc_stop = emu.add_machine_stop_notifier(function()
  local list = {}
  for a in pairs(seen) do list[#list + 1] = a end
  table.sort(list)
  local f = io.open(OUT, "w")
  for _, a in ipairs(list) do
    f:write(string.format("%06X\n", a))
  end
  f:close()
  print(string.format("[cypc] wrote %s: %d distinct addresses "
                      .. "(%d fetches, %d data reads)",
                      OUT, #list, nfetch, ndata))
end)

print("[cypc] armed")
