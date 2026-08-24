-- What is on a real Cybiko's screen?
--
-- Watches the two HD66421 ports and keeps the display RAM the same way
-- src/lcd.c does, so the frame this writes and the frame the recompiled
-- machine draws are directly comparable -- which is the point. A renderer
-- that agrees with itself proves nothing.
--
--   mame cybikov1 -video none -sound none -seconds_to_run N \
--        -autoboot_script tools/mame_lcd.lua
--
-- Writes cylcd.pgm (160x100, four greys) and prints the panel as characters.

local OUT = os.getenv("CYLCD_OUT") or "cylcd.pgm"

local W, H, STRIDE = 160, 100, 40
local PORT, DATA = 0x600000, 0x600001
local R_X, R_Y, R_DATA = 2, 3, 4

local prog = manager.machine.devices[":maincpu"].spaces["program"]
local WIDTH = prog.data_width

local index, reg, vram, writes = 0, {}, {}, 0
for i = 0, 31 do reg[i] = 0 end
for i = 0, H * STRIDE - 1 do vram[i] = 0 end

local function poke(addr, v)
  if addr == PORT then
    index = v & 0x1F
  elseif addr == DATA then
    if index == R_DATA then
      local x, y = reg[R_X], reg[R_Y]
      if x < STRIDE and y < H then vram[y * STRIDE + x] = v end
      reg[R_X] = (x + 1) % STRIDE
      writes = writes + 1
    else
      reg[index] = v
    end
  end
end

_G.cy_lcd_tap = prog:install_write_tap(PORT, DATA, "cy_lcd",
  function(offset, data, mask)
    for shift = WIDTH - 8, 0, -8 do
      if ((mask >> shift) & 0xFF) ~= 0 then
        poke(offset + ((WIDTH - 8 - shift) // 8), (data >> shift) & 0xFF)
      end
    end
  end)

_G.cy_lcd_stop = emu.add_machine_stop_notifier(function()
  local f = io.open(OUT, "wb")
  f:write(string.format("P5\n%d %d\n3\n", W, H))
  local glyph = { [0] = "@", "%", ".", " " }
  local rows = {}
  for y = 0, H - 1 do
    local raw, txt = {}, {}
    for x = 0, W - 1 do
      local b = vram[y * STRIDE + (x >> 2)]
      local dot = (b >> (2 * (3 - (x & 3)))) & 3
      raw[#raw + 1] = string.char(dot)
      if x % 2 == 0 then txt[#txt + 1] = glyph[dot] end
    end
    f:write(table.concat(raw))
    if y % 2 == 0 then rows[#rows + 1] = table.concat(txt) end
  end
  f:close()
  for _, r in ipairs(rows) do print("[cylcd] " .. r) end
  print(string.format("[cylcd] %s, %d data writes, display %s",
                      OUT, writes, (reg[0] & 0x40) ~= 0 and "on" or "off"))
end)

print("[cylcd] armed")
