"""NC Viewer 아이콘 생성기 (Pillow) - 다중 해상도 .ico 출력"""
from PIL import Image, ImageDraw

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 둥근 배경 (다크 IDE 톤)
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=44, fill=(33, 37, 43, 255))
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=44, outline=(70, 78, 90, 255), width=3)

# 원점
ox, oy = 74, 188
# Z축 (청색, 위로)
d.line([ox, oy, ox, 66], fill=(90, 120, 255, 255), width=6)
# X축 (적색, 오른쪽 아래 원근)
d.line([ox, oy, 210, 214], fill=(255, 70, 70, 255), width=6)
# Y축 (녹색, 오른쪽 위 원근)
d.line([ox, oy, 214, 120], fill=(70, 210, 90, 255), width=6)

# 3D 가공 경로(툴패스) - 주황색 폴리라인
path = [(96, 150), (150, 128), (150, 92), (196, 92), (196, 150), (128, 168), (128, 200)]
d.line(path, fill=(255, 140, 0, 255), width=7, joint="curve")
for p in path:
    d.ellipse([p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5], fill=(255, 180, 60, 255))

# 커서 스피어(노란 공구 위치)
cx, cy = path[-1]
d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=(255, 235, 0, 255),
          outline=(180, 150, 0, 255), width=2)

sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save("nc_viewer.ico", sizes=sizes)
print("nc_viewer.ico 생성 완료")
