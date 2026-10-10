// English / Thai switch for the model workbench (index.html). The page is plain DOM written by one big script, so the
// translation is applied to its text nodes and attributes (and re-applied when the script rewrites them).
// The language is shared with the dashboard (localStorage key fd_lang).
const TH = {
  'Basemap': 'แผนที่ฐาน', 'Streets': 'ถนน', 'Satellite': 'ดาวเทียม', 'Light': 'สว่าง', 'Dark': 'มืด', 'OpenStreetMap': 'OpenStreetMap',
  'Hide isolated patches under about 1 km²': 'ซ่อนพื้นที่น้ำท่วมโดด ๆ ที่เล็กกว่าประมาณ 1 ตร.กม.',
  'Reset view': 'รีเซ็ตมุมมอง', 'North up': 'หันทิศเหนือขึ้น', 'Full screen': 'เต็มจอ',
  'Outside the model domain': 'อยู่นอกขอบเขตแบบจำลอง', 'Outside the model domain.': 'อยู่นอกขอบเขตแบบจำลอง',
  'Map failed to start:': 'เริ่มแผนที่ไม่สำเร็จ:',
  'Bangkok Flood Surrogate': 'แบบจำลองตัวแทนน้ำท่วมกรุงเทพฯ',
  'Neural emulator of the ANUGA rain + tide flood model · 150 m grid · 15-min steps': 'โครงข่ายประสาทเทียมเลียนแบบแบบจำลองน้ำท่วม ANUGA (ฝน + น้ำขึ้นน้ำลง) · กริด 150 ม. · ก้าวเวลา 15 นาที',
  'Flood dashboard →': 'แดชบอร์ดน้ำท่วม →', 'Simulate': 'จำลองสถานการณ์', 'Observations & calibration': 'การสังเกตการณ์และการปรับเทียบ',
  '1 · Inputs': '1 · ข้อมูลนำเข้า', 'ANUGA scenario': 'สถานการณ์ ANUGA', 'Input files': 'ไฟล์ข้อมูลนำเข้า', 'Design storm': 'พายุออกแบบ', 'Paste series': 'วางอนุกรมข้อมูล',
  'Scenario (rain + tide exactly as ANUGA was forced)': 'สถานการณ์ (ฝน + น้ำขึ้นน้ำลงตรงตามที่ใช้บังคับ ANUGA)',
  'Event in inputs/ (X1, X2 have no ANUGA result: pure prediction)': 'เหตุการณ์ใน inputs/ (X1, X2 ไม่มีผล ANUGA: เป็นการพยากรณ์ล้วน)',
  'Tide variant': 'รูปแบบน้ำขึ้นน้ำลง', 'High tide (HT)': 'น้ำขึ้นสูง (HT)', 'Low tide (LT)': 'น้ำลงต่ำ (LT)',
  'Total rain': 'ปริมาณฝนรวม', 'Rain duration': 'ระยะเวลาฝน', 'Peak position in the burst': 'ตำแหน่งจุดสูงสุดในห่าฝน', 'Hyetograph shape': 'รูปแบบกราฟฝน',
  'Peaked (Chicago-like)': 'แหลม (แบบชิคาโก)', 'Triangular': 'สามเหลี่ยม', 'Uniform': 'สม่ำเสมอ', 'Simulate after rain ends': 'จำลองต่อหลังฝนหยุด',
  'Tide amplitude ×': 'แอมพลิจูดน้ำขึ้นน้ำลง ×', 'High water relative to rain peak': 'เวลาน้ำขึ้นสูงสุดเทียบกับจุดฝนสูงสุด',
  'Rain, mm per 15 min (comma / space / newline separated)': 'ฝน มม. ต่อ 15 นาที (คั่นด้วยจุลภาค / เว้นวรรค / ขึ้นบรรทัดใหม่)',
  'Tide, m MSL (optional; stretched to the rain length; blank = synthetic HT at rain peak)': 'น้ำขึ้นน้ำลง ม. รทก. (ไม่บังคับ; ยืดให้เท่าความยาวฝน; เว้นว่าง = น้ำขึ้นสูงสังเคราะห์ที่จุดฝนสูงสุด)',
  'leave blank for the synthetic high-tide curve': 'เว้นว่างเพื่อใช้เส้นโค้งน้ำขึ้นสูงสังเคราะห์',
  'Run model': 'รันแบบจำลอง', 'Running the surrogate…': 'กำลังรันแบบจำลองตัวแทน…',
  'Model accuracy (vs ANUGA)': 'ความแม่นยำของแบบจำลอง (เทียบกับ ANUGA)', 'No metrics file yet.': 'ยังไม่มีไฟล์ตัวชี้วัด', 'About this model': 'เกี่ยวกับแบบจำลองนี้',
  '2 · Results': '2 · ผลลัพธ์', 'Pick an input and press': 'เลือกข้อมูลนำเข้าแล้วกด',
  '3 · Maps': '3 · แผนที่', 'Predicted depth': 'ความลึกจากแบบจำลอง', 'ANUGA depth': 'ความลึก ANUGA', 'Error': 'ความคลาดเคลื่อน', 'Pred. speed': 'ความเร็วจากแบบจำลอง',
  'Max depth (pred)': 'ความลึกสูงสุด (แบบจำลอง)', 'Max depth (ANUGA)': 'ความลึกสูงสุด (ANUGA)', 'Terrain': 'ภูมิประเทศ', 'Curve no.': 'ค่า Curve no.', 'Manning n': 'ค่า Manning n', 'Coast dist.': 'ระยะจากชายฝั่ง',
  'side-by-side with ANUGA': 'วางเทียบข้างกับ ANUGA', 'Show depth ≥': 'แสดงความลึก ≥', 'Sentinel-1 overlay: off': 'ซ้อนภาพ Sentinel-1: ปิด',
  'Click the map to plot the depth time series at that cell. Grid: EPSG:32647 (UTM 47N), 150 m cells.': 'คลิกแผนที่เพื่อแสดงอนุกรมเวลาความลึกที่เซลล์นั้น กริด: EPSG:32647 (UTM 47N) เซลล์ 150 ม.',
  '4 · Time series': '4 · อนุกรมเวลา', 'Forcing (model inputs)': 'ปัจจัยบังคับ (ข้อมูลนำเข้า)', 'rain mm/15 min': 'ฝน มม./15 นาที', 'tide m (right axis)': 'น้ำขึ้นน้ำลง ม. (แกนขวา)',
  'Flooded area ≥ 0.15 m (km²)': 'พื้นที่น้ำท่วม ≥ 0.15 ม. (ตร.กม.)', 'surrogate': 'แบบจำลองตัวแทน', '≥ 0.5 m (surrogate)': '≥ 0.5 ม. (แบบจำลองตัวแทน)',
  'Depth at clicked cell (m)': 'ความลึกที่เซลล์ที่คลิก (ม.)', 'Run the model to see this chart.': 'รันแบบจำลองเพื่อดูกราฟนี้', 'Click a cell on the map.': 'คลิกเซลล์บนแผนที่',
  'Download:': 'ดาวน์โหลด:', 'time series (CSV)': 'อนุกรมเวลา (CSV)', 'predicted max depth (ESRI ASCII grid)': 'ความลึกสูงสุดจากแบบจำลอง (ESRI ASCII grid)', 'ANUGA max depth (grid)': 'ความลึกสูงสุด ANUGA (grid)',
  'Rain total': 'ฝนรวม', 'Peak intensity': 'ความเข้มฝนสูงสุด', 'Peak flooded area ≥0.15 m': 'พื้นที่น้ำท่วมสูงสุด ≥0.15 ม.', 'Peak area ≥0.5 m': 'พื้นที่สูงสุด ≥0.5 ม.', '99th pct max depth': 'ความลึกสูงสุดที่เปอร์เซนไทล์ 99',
  'ANUGA peak area': 'พื้นที่สูงสุดของ ANUGA', 'Depth RMSE': 'RMSE ความลึก', 'RMSE where wet': 'RMSE บริเวณเปียก', 'Extent CSI': 'CSI ขอบเขตน้ำท่วม', 'Max-depth map RMSE': 'RMSE แผนที่ความลึกสูงสุด',
  'mm': 'มม.', 'mm/15 min': 'มม./15 นาที', 'm': 'ม.', 'km²': 'ตร.กม.', 'h': 'ชม.',
  'Surrogate depth': 'ความลึกจากแบบจำลองตัวแทน', 'Error (surrogate − ANUGA)': 'ความคลาดเคลื่อน (แบบจำลองตัวแทน − ANUGA)', 'Surrogate speed': 'ความเร็วจากแบบจำลองตัวแทน', 'ANUGA speed': 'ความเร็ว ANUGA',
  'Max depth, surrogate': 'ความลึกสูงสุด แบบจำลองตัวแทน', 'Max depth, ANUGA': 'ความลึกสูงสุด ANUGA', 'Sentinel-1 vs surrogate': 'Sentinel-1 เทียบกับแบบจำลองตัวแทน', 'Sentinel-1 flood extent': 'ขอบเขตน้ำท่วมจาก Sentinel-1',
  'Sentinel-1-derived depth': 'ความลึกที่คำนวณจาก Sentinel-1', 'maximum over the event': 'ค่าสูงสุดตลอดเหตุการณ์', 'Terrain (m, EGM2008)': 'ภูมิประเทศ (ม., EGM2008)', 'SCS curve number': 'SCS curve number', "Manning's n": 'ค่า Manning n', 'Distance to coast (km)': 'ระยะจากชายฝั่ง (กม.)',
  '(log scale)': '(มาตราส่วนลอการิทึม)', 'Held-out test events (never seen in training)': 'เหตุการณ์ทดสอบที่กันไว้ (ไม่เคยเห็นตอนฝึก)', 'Training events': 'เหตุการณ์ที่ใช้ฝึก', 'Your uploaded events': 'เหตุการณ์ที่คุณอัปโหลด',
  'Test mean': 'ค่าเฉลี่ยชุดทดสอบ', 'Train mean': 'ค่าเฉลี่ยชุดฝึก', 'test': 'ทดสอบ', 'train': 'ฝึก', 'Event': 'เหตุการณ์', 'RMSE m': 'RMSE ม.', 'RMSE wet': 'RMSE บริเวณเปียก', 'Peak area err': 'ความคลาดเคลื่อนพื้นที่สูงสุด',
  'Map frame failed to load (run expired? press Run again).': 'โหลดภาพแผนที่ไม่สำเร็จ (ผลรันหมดอายุ? กดรันอีกครั้ง)',
  'Observations belong to an event; its rain and tide drive the model at the observation time.': 'การสังเกตการณ์สังกัดเหตุการณ์หนึ่ง ฝนและน้ำขึ้นน้ำลงของเหตุการณ์นั้นใช้ขับเคลื่อนแบบจำลอง ณ เวลาสังเกต',
  'New event from a rain CSV…': 'สร้างเหตุการณ์ใหม่จากไฟล์ฝน CSV…', 'Name': 'ชื่อ', 'Rain CSV: datetime_local, precip_mm_per_15min (15-min steps)': 'ไฟล์ฝน CSV: datetime_local, precip_mm_per_15min (ก้าว 15 นาที)',
  'Tide CSV (optional: datetime, stage_m; blank = synthetic high tide at the rain peak)': 'ไฟล์น้ำขึ้นน้ำลง CSV (ไม่บังคับ: datetime, stage_m; เว้นว่าง = น้ำขึ้นสูงสังเคราะห์ที่จุดฝนสูงสุด)', 'Create event': 'สร้างเหตุการณ์',
  'CCTV readings': 'ค่าอ่านจาก CCTV', 'Single reading': 'ค่าเดียว', 'CSV import': 'นำเข้า CSV', 'Time of the reading (local, UTC+7)': 'เวลาที่อ่านค่า (เวลาท้องถิ่น UTC+7)', 'Latitude': 'ละติจูด', 'Longitude': 'ลองจิจูด',
  '…or click the map to pick the camera cell.': '…หรือคลิกแผนที่เพื่อเลือกเซลล์ของกล้อง', 'Depth (m)': 'ความลึก (ม.)', 'Low (m)': 'ต่ำ (ม.)', 'High (m)': 'สูง (ม.)', 'Confidence 0-1': 'ความมั่นใจ 0-1',
  'Before depth (m)': 'ความลึกก่อนหน้า (ม.)', 'Camera id': 'รหัสกล้อง', 'Before image (optional)': 'ภาพก่อน (ไม่บังคับ)', 'After image (optional)': 'ภาพหลัง (ไม่บังคับ)', 'Notes': 'หมายเหตุ', 'Add reading': 'เพิ่มค่า',
  'CSV columns: lat, lon, time_local, depth_m; optional depth_low_m, depth_high_m, confidence, before_depth_m, camera, notes, event_id, before_image, after_image': 'คอลัมน์ CSV: lat, lon, time_local, depth_m; ไม่บังคับ depth_low_m, depth_high_m, confidence, before_depth_m, camera, notes, event_id, before_image, after_image',
  'Images named in the CSV (optional, select several)': 'ภาพที่ระบุชื่อใน CSV (ไม่บังคับ เลือกได้หลายไฟล์)', 'Import CSV': 'นำเข้า CSV', 'auto': 'อัตโนมัติ', 'accepted': 'ยอมรับ', 'flagged': 'ทำเครื่องหมาย', 'rejected': 'ปฏิเสธ',
  'Sentinel-1 SAR': 'ภาพ SAR Sentinel-1', 'Acquisition time (UTC)': 'เวลาที่บันทึกภาพ (UTC)', 'Content': 'เนื้อหา', 'Backscatter VV or VH (sigma0, dB or linear)': 'ค่าการกระเจิงกลับ VV หรือ VH (sigma0, dB หรือเชิงเส้น)',
  'Water / flood mask (1 = water)': 'หน้ากากน้ำ / น้ำท่วม (1 = น้ำ)', 'Post-event GeoTIFF': 'GeoTIFF หลังเหตุการณ์', 'Pre-event GeoTIFF (optional, same polarisation; removes permanent water)': 'GeoTIFF ก่อนเหตุการณ์ (ไม่บังคับ โพลาไรเซชันเดียวกัน; ใช้ตัดแหล่งน้ำถาวร)',
  'Label (optional)': 'ป้ายกำกับ (ไม่บังคับ)', 'Process image': 'ประมวลผลภาพ', 'Self-calibration': 'การปรับเทียบตนเอง', 'Auto-improve whenever observations are added or changed': 'ปรับปรุงอัตโนมัติเมื่อมีการเพิ่มหรือแก้ไขการสังเกตการณ์',
  'Steps': 'จำนวนก้าว', 'ANUGA anchor': 'ตัวยึด ANUGA', 'force promote': 'บังคับเลื่อนใช้งาน', 'Run calibration round': 'รันรอบการปรับเทียบ',
  "Each round fine-tunes a copy of the active model on accepted (weight 1) and flagged (weight 0.5) observations, while an anchor loss keeps it close to the ANUGA runs. It is scored on held-out CCTV readings (30%) and held-out 3.6 km blocks of every SAR map, and becomes the active model only if it scores better there and its error against ANUGA stays within 1.5× of the current model's.":
    'แต่ละรอบจะปรับจูนสำเนาของแบบจำลองที่ใช้งานด้วยการสังเกตที่ยอมรับ (น้ำหนัก 1) และที่ทำเครื่องหมาย (น้ำหนัก 0.5) โดยมีค่าสูญเสียแบบตัวยึดให้ใกล้เคียงผลรัน ANUGA แล้วให้คะแนนจากค่า CCTV ที่กันไว้ (30%) และบล็อก 3.6 กม. ที่กันไว้ของทุกแผนที่ SAR จะกลายเป็นแบบจำลองที่ใช้งานก็ต่อเมื่อได้คะแนนดีกว่าและความคลาดเคลื่อนเทียบ ANUGA ไม่เกิน 1.5 เท่าของแบบจำลองปัจจุบัน',
  'Map': 'แผนที่', 'Terrain + readings': 'ภูมิประเทศ + ค่าที่อ่านได้', 'SAR flood extent': 'ขอบเขตน้ำท่วมจาก SAR', 'SAR-derived depth': 'ความลึกที่คำนวณจาก SAR', 'SAR vs active model': 'SAR เทียบกับแบบจำลองที่ใช้งาน',
  'Observations': 'การสังเกตการณ์', 'show all events': 'แสดงทุกเหตุการณ์', 'Loading…': 'กำลังโหลด…', 'Selected observation': 'การสังเกตการณ์ที่เลือก', 'Pick a row in the table.': 'เลือกแถวในตาราง',
  'Model versions': 'เวอร์ชันแบบจำลอง', 'Calibration rounds': 'รอบการปรับเทียบ', 'No rounds yet.': 'ยังไม่มีรอบการปรับเทียบ', 'Idle.': 'ว่าง',
  'No observations for this event yet. Add CCTV readings or a Sentinel-1 image on the left.': 'ยังไม่มีการสังเกตการณ์ของเหตุการณ์นี้ เพิ่มค่าจาก CCTV หรือภาพ Sentinel-1 ทางด้านซ้าย',
  'Type': 'ประเภท', 'Time (local)': 'เวลา (ท้องถิ่น)', 'Where': 'ตำแหน่ง', 'Value': 'ค่า', 'Checks': 'การตรวจสอบ', 'Status': 'สถานะ', 'view': 'ดู', 'delete': 'ลบ', 'activate': 'เปิดใช้', 'Version': 'เวอร์ชัน', 'Created': 'สร้างเมื่อ',
  'From': 'มาจาก', 'Obs': 'จำนวนสังเกต', 'Validation score': 'คะแนนตรวจสอบ', 'ANUGA RMSE': 'RMSE เทียบ ANUGA', 'Round': 'รอบ', 'Score active → cand.': 'คะแนน ปัจจุบัน → ตัวเลือก', 'SAR CSI': 'CSI ของ SAR', 'CCTV MAE': 'MAE ของ CCTV', 'Result': 'ผลลัพธ์',
  'kept': 'คงเดิม', 'Depth': 'ความลึก', 'Range': 'ช่วง', 'Confidence': 'ความมั่นใจ', 'Cell': 'เซลล์', 'SAR flooded': 'พื้นที่ท่วมจาก SAR', 'Model flooded (same cells)': 'พื้นที่ท่วมจากแบบจำลอง (เซลล์เดียวกัน)', 'CSI non-urban': 'CSI นอกเมือง', 'POD urban': 'POD ในเมือง',
  'Auto status: rejected if a hard check fails, flagged (half weight) if a soft check fails. Override per row.': 'สถานะอัตโนมัติ: ปฏิเสธถ้าไม่ผ่านการตรวจแบบเข้มงวด ทำเครื่องหมาย (น้ำหนักครึ่งหนึ่ง) ถ้าไม่ผ่านการตรวจแบบอ่อน แก้ไขได้ทีละแถว',
  'Lower validation score is better: mean of (1 − SAR CSI) and CCTV MAE / 0.5 m on the held-out part. Activating an older version rolls the model back.': 'คะแนนตรวจสอบยิ่งต่ำยิ่งดี: ค่าเฉลี่ยของ (1 − CSI ของ SAR) และ MAE ของ CCTV / 0.5 ม. บนส่วนที่กันไว้ การเปิดใช้เวอร์ชันเก่าคือการย้อนแบบจำลองกลับ',
  'Dots: CCTV readings of this event (green accepted, orange flagged, red rejected). Click the map to pick a camera cell.': 'จุด: ค่าจาก CCTV ของเหตุการณ์นี้ (เขียว = ยอมรับ ส้ม = ทำเครื่องหมาย แดง = ปฏิเสธ) คลิกแผนที่เพื่อเลือกเซลล์ของกล้อง',
  'Idle': 'ว่าง', 'hard': 'เข้มงวด',
};
// strings with numbers / names in them
const PAT = [
  [/^running on (.+?)(?: · model (.+))?$/, (m) => `ทำงานบน ${m[1]}${m[2] ? ' · โมเดล ' + m[2] : ''}`],
  [/^Done: (\d+) steps predicted in ([\d.]+) s on (.+)\.$/, (m) => `เสร็จแล้ว: พยากรณ์ ${m[1]} ก้าวใน ${m[2]} วินาที บน ${m[3]}`],
  [/^\+([\d.]+) h(?: · (.*))?$/, (m) => `+${m[1]} ชม.${m[2] ? ' · ' + m[2] : ''}`],
  [/^Held-out event · total ([\d.]+) mm · peak ([\d.]+) mm\/15 min · ([\d.]+) h$/, (m) => `เหตุการณ์ทดสอบที่กันไว้ · รวม ${m[1]} มม. · สูงสุด ${m[2]} มม./15 นาที · ${m[3]} ชม.`],
  [/^Training event · total ([\d.]+) mm · peak ([\d.]+) mm\/15 min · ([\d.]+) h$/, (m) => `เหตุการณ์ที่ใช้ฝึก · รวม ${m[1]} มม. · สูงสุด ${m[2]} มม./15 นาที · ${m[3]} ชม.`],
  [/^Uploaded event · starts (.+) · (\d+) observation\(s\)$/, (m) => `เหตุการณ์ที่อัปโหลด · เริ่ม ${m[1]} · ${m[2]} การสังเกต`],
  [/^(.+)  \(no ANUGA run\)$/, (m) => `${m[1]}  (ไม่มีผลรัน ANUGA)`],
  [/^starts (.+)$/, (m) => `เริ่ม ${m[1]}`],
  [/^(.+) steps? \(([\d.]+) h\)$/, (m) => `${m[1]} ก้าว (${m[2]} ชม.)`],
  [/^(\d+) steps \(([\d.]+) h\)$/, (m) => `${m[1]} ก้าว (${m[2]} ชม.)`],
  [/^Imported (\d+) reading\(s\)\.$/, (m) => `นำเข้าแล้ว ${m[1]} ค่า`],
  [/^Uploading image (\d+)\/(\d+)…$/, (m) => `กำลังอัปโหลดภาพ ${m[1]}/${m[2]}…`],
  [/^Created event (.+)\. It is also selectable under Simulate → ANUGA scenario\.$/, (m) => `สร้างเหตุการณ์ ${m[1]} แล้ว เลือกใช้ได้ที่ จำลองสถานการณ์ → สถานการณ์ ANUGA`],
  [/^Added: ([\d.–]+) m at row (\d+), col (\d+) → (.+)\.$/, (m) => `เพิ่มแล้ว: ${m[1]} ม. ที่แถว ${m[2]} คอลัมน์ ${m[3]} → ${m[4]}`],
  [/^Done: ([\d.]+) km² flooded of ([\d.]+) km² covered → (.+)\.$/, (m) => `เสร็จแล้ว: ท่วม ${m[1]} ตร.กม. จากพื้นที่ครอบคลุม ${m[2]} ตร.กม. → ${m[3]}`],
  [/^Picked cell row (\d+), col (\d+) \(lat\/lon are filled in when saved\)\. Type lat\/lon instead to override\.$/, (m) => `เลือกเซลล์แถว ${m[1]} คอลัมน์ ${m[2]} (ละติจูด/ลองจิจูดจะถูกเติมเมื่อบันทึก) พิมพ์ละติจูด/ลองจิจูดเองเพื่อแทนที่`],
  [/^Total rain ([\d.]+) mm is above the largest training event \(([\d.]+) mm\): extrapolation\.$/, (m) => `ปริมาณฝนรวม ${m[1]} มม. สูงกว่าเหตุการณ์ฝึกที่ใหญ่ที่สุด (${m[2]} มม.): เป็นการคาดการณ์นอกช่วงข้อมูล`],
  [/^Peak ([\d.]+) mm\/15 min is above anything seen in training \(([\d.]+)\)\.$/, (m) => `ความเข้มสูงสุด ${m[1]} มม./15 นาที สูงกว่าที่เคยพบในชุดฝึก (${m[2]})`],
  [/^Event is longer than any training event \(([\d.]+) h\)\.$/, (m) => `เหตุการณ์ยาวกว่าเหตุการณ์ฝึกทุกชุด (${m[1]} ชม.)`],
  [/^Training used the high-tide \(HT\) variant only; LT results are untested\.$/, () => 'ชุดฝึกใช้เฉพาะน้ำขึ้นสูง (HT) ผลของ LT จึงยังไม่ได้ทดสอบ'],
  [/^Tide is outside the synthetic HT range used in training \((.+)\)\.$/, (m) => `น้ำขึ้นน้ำลงอยู่นอกช่วง HT สังเคราะห์ที่ใช้ฝึก (${m[1]})`],
  [/^Outside the model domain\.$/, () => 'อยู่นอกขอบเขตแบบจำลอง'],
  [/^UTM (.+) E, (.+) N · ground (.+) m · CN (.+) · n (.+) · (.+) km from coast · peak depth (.+) m$/, (m) => `UTM ${m[1]} E, ${m[2]} N · พื้นดิน ${m[3]} ม. · CN ${m[4]} · n ${m[5]} · ห่างชายฝั่ง ${m[6]} กม. · ความลึกสูงสุด ${m[7]} ม.`],
  [/^SAR (.+) · (vs surrogate|extent|derived depth)$/, (m) => `SAR ${m[1]} · ${{ 'vs surrogate': 'เทียบแบบจำลอง', extent: 'ขอบเขต', 'derived depth': 'ความลึกที่คำนวณ' }[m[2]]}`],
  [/^(\d+) CCTV, (\d+) SAR$/, (m) => `CCTV ${m[1]}, SAR ${m[2]}`],
  [/^([\d.]+) km² flooded$/, (m) => `ท่วม ${m[1]} ตร.กม.`],
  [/^(\d+) obs$/, (m) => `${m[1]} สังเกต`],
  [/^auto \((.+)\)$/, (m) => `อัตโนมัติ (${TH[m[1]] || m[1]})`],
  [/^(.+) promoted$/, (m) => `${m[1]} ถูกเลื่อนใช้งาน`],
  [/^RMSE over all valid cells and time steps; "wet" = cells where ANUGA depth ≥ 0\.15 m\. CSI = hits \/ \(hits \+ misses \+ false alarms\) for the ≥ 0\.15 m flood extent\. Blue rows were never seen during training\.$/,
    () => 'RMSE คำนวณจากทุกเซลล์และทุกก้าวเวลาที่ใช้ได้; "เปียก" = เซลล์ที่ความลึก ANUGA ≥ 0.15 ม. CSI = ถูกต้อง / (ถูกต้อง + พลาด + แจ้งเตือนผิด) ของขอบเขตน้ำท่วม ≥ 0.15 ม. แถวสีน้ำเงินคือชุดที่ไม่เคยเห็นระหว่างฝึก'],
];

let lang = 'en';
try { const s = localStorage.getItem('fd_lang'); if (s === 'th' || s === 'en') lang = s; else if ((navigator.language || '').toLowerCase().startsWith('th')) lang = 'th'; } catch (e) {}
try { const q = new URLSearchParams(location.search).get('lang'); if (q === 'th' || q === 'en') lang = q; } catch (e) {}

export function translate(text) {
  if (lang !== 'th' || !text) return text;
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(text);
  const core = m[2];
  if (!core) return text;
  let out = TH[core];
  if (out === undefined) { for (const [re, fn] of PAT) { const mm = re.exec(core); if (mm) { out = fn(mm); break; } } }
  return out === undefined ? text : m[1] + out + m[3];
}
window.wbT = translate;

const orig = new WeakMap();      // node -> English original
let writing = false;
function tNode(n) {
  if (n.nodeType === 3) {
    const p = n.parentNode && n.parentNode.nodeName;
    if (p === 'SCRIPT' || p === 'STYLE') return;
    const cur = n.nodeValue;
    const known = orig.get(n);
    const base = known && translate(known.en) === cur ? known.en : cur;   // the page may have rewritten it since
    const out = lang === 'th' ? translate(base) : base;
    if (out !== cur) { writing = true; n.nodeValue = out; writing = false; }
    if (out !== base || known) orig.set(n, { en: base });
  } else if (n.nodeType === 1) {
    for (const a of ['placeholder', 'title', 'alt', 'aria-label']) {
      if (!n.hasAttribute(a)) continue;
      const key = 'data-en-' + a, cur = n.getAttribute(a), en = n.hasAttribute(key) ? n.getAttribute(key) : cur;
      if (!n.hasAttribute(key) && lang === 'th' && translate(cur) !== cur) n.setAttribute(key, cur);
      const out = lang === 'th' ? translate(en) : en;
      if (out !== cur) { writing = true; n.setAttribute(a, out); writing = false; }
    }
  }
}
function walk(root) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  let n = w.currentNode; tNode(n);
  while ((n = w.nextNode())) tNode(n);
}
let queued = false;
const pending = new Set();
function flush() {
  queued = false;
  for (const n of pending) { if (n.nodeType === 3) tNode(n); else walk(n); }
  pending.clear();
}
const mo = new MutationObserver((recs) => {
  if (writing) return;
  for (const r of recs) {
    if (r.type === 'characterData') pending.add(r.target);
    else if (r.type === 'attributes') { if (!/^data-en-/.test(r.attributeName)) pending.add(r.target); }
    else r.addedNodes.forEach((n) => pending.add(n));
  }
  if (!queued) { queued = true; requestAnimationFrame(flush); }
});

export function setLang(l) {
  lang = l === 'th' ? 'th' : 'en';
  try { localStorage.setItem('fd_lang', lang); } catch (e) {}
  document.documentElement.lang = lang;
  document.title = translate('Bangkok Flood Surrogate');
  walk(document.body);
  document.querySelectorAll('.lang button').forEach((b) => b.classList.toggle('on', b.dataset.lang === lang));
  document.dispatchEvent(new CustomEvent('wb-lang', { detail: lang }));
}
export function init() {
  mo.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'alt'] });
  document.querySelectorAll('.lang button').forEach((b) => (b.onclick = () => setLang(b.dataset.lang)));
  setLang(lang);
}
