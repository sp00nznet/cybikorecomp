-- Record every byte the Cybiko writes, in order, to diff against.
--
-- A PC trace cannot be trusted on this CPU: the H8S prefetches, so a read tap
-- sees the word after a taken branch even though it never executes, and the
-- fetch order is not the execution order. Writes have no such problem. A store
-- happens when, and only when, an instruction really runs.
--
-- Everything is decomposed to single bytes, because the CPU's 32-bit stores
-- reach the bus as narrower accesses and the two sides would otherwise
-- disagree about width while agreeing about content.
--
--   mame cybikov1 -video none -sound none -seconds_to_run N \
--        -autoboot_script tools/mame_writetrace.lua
--
-- Writes cywrites.bin: 8 bytes per byte-write, big-endian -- addr(4) val(4).

local OUT   = os.getenv("CYWR_OUT") or "cywrites.bin"
local LIMIT = tonumber(os.getenv("CYWR_N") or "200000")

local cpu  = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]

local f = io.open(OUT, "wb")
local n = 0
local buf = {}

local function be32(v)
  v = v & 0xFFFFFFFF
  return string.char((v >> 24) & 0xFF, (v >> 16) & 0xFF,
                     (v >> 8) & 0xFF, v & 0xFF)
end

local function emit(addr, val)
  n = n + 1
  buf[#buf + 1] = be32(addr)
  buf[#buf + 1] = be32(val)
  if #buf >= 4000 then
    f:write(table.concat(buf))
    buf = {}
  end
end

-- The lane layout depends on the bus width, not on 32 bits. This space is
-- 16-bit, so a full-word mask of 0xFFFF covers bytes 0 and 1 of the offset --
-- assuming a 32-bit bus puts every address two bytes too high, which shows up
-- as a stream whose values are right and whose addresses are all off by two.
local WIDTH = prog.data_width

_G.cy_wr_tap = prog:install_write_tap(0x000000, 0xFFFFFF, "cy_wr",
  function(offset, data, mask)
    if n >= LIMIT then return end
    -- Most significant lane first, so the order matches a big-endian store.
    for shift = WIDTH - 8, 0, -8 do
      if ((mask >> shift) & 0xFF) ~= 0 then
        emit(offset + ((WIDTH - 8 - shift) // 8), (data >> shift) & 0xFF)
      end
    end
  end)

_G.cy_wr_stop = emu.add_machine_stop_notifier(function()
  if #buf > 0 then f:write(table.concat(buf)) end
  f:close()
  print(string.format("[cywr] wrote %s: %d byte-writes", OUT, n))
end)

print("[cywr] armed, limit " .. LIMIT)
