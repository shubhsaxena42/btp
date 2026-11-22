from PIL import Image, ImageOps, ImageChops
from playwright.sync_api import sync_playwright
W,H=1840,880
def fit(im,out):
    w,h=im.size; r=W/H
    if w/h>r: nh=round(w/r); c=Image.new('RGB',(w,nh),'white'); c.paste(im,(0,(nh-h)//2)); im=c
    elif w/h<r: nw=round(h*r); c=Image.new('RGB',(nw,h),'white'); c.paste(im,((nw-w)//2,0)); im=c
    im.resize((W,H),Image.LANCZOS).save(out); print(out)
def trim(im,pad=20):
    bg=Image.new('RGB',im.size,'white'); bb=ImageChops.difference(im,bg).getbbox()
    return im.crop((max(bb[0]-pad,0),max(bb[1]-pad,0),min(bb[2]+pad,im.width),min(bb[3]+pad,im.height)))
# fig1: dashboard down to the bottom of the chart cards
with sync_playwright() as p:
    b=p.chromium.launch(); c=b.new_context(viewport={'width':1440,'height':900},device_scale_factor=2)
    pg=c.new_page(); pg.goto('http://127.0.0.1:5050/lang/en'); pg.goto('http://127.0.0.1:5050/'); pg.wait_for_load_state('networkidle')
    boxes=[pg.locator('.card').nth(i).bounding_box() for i in range(pg.locator('.card').count())]
    bottom=sorted(bx['y']+bx['height'] for bx in boxes)
    chart=[bx for bx in boxes if bx['y']>500][:2]
    yb=max(bx['y']+bx['height'] for bx in chart)+8
    full=Image.open(__import__('io').BytesIO(pg.screenshot(full_page=True))).convert('RGB'); b.close()
fit(full.crop((int(310*2),0,int(1130*2+250),int(yb*2))) if False else full.crop((0,0,2880,int(yb*2))),'shots/fig1_dashboard.png')
f2=Image.open('shots/_fig2_full.png').convert('RGB')
fit(f2.crop((210,400,2665,1745)),'shots/fig2_gi_check.png')
f3=Image.open('shots/_fig3_full.png').convert('RGB')
fit(f3.crop((int(360*2),int(86*2),int(1082*2),int(775*2))),'shots/fig4_tmp.png' if False else 'shots/fig3_invoice.png')
lab=trim(Image.open('shots/_label.png').convert('RGB'))
ph=Image.open('shots/_portal.png').convert('RGB')
th=820
lab=lab.resize((round(lab.width*th/lab.height),th),Image.LANCZOS)
ph=ph.resize((round(ph.width*th/ph.height),th),Image.LANCZOS); ph=ImageOps.expand(ph,2,'#b0b0b0')
cv=Image.new('RGB',(W,H),'white'); tw=lab.width+40+ph.width; x=(W-tw)//2
cv.paste(lab,(x,(H-lab.height)//2)); cv.paste(ph,(x+lab.width+40,(H-ph.height)//2)); cv.save('shots/fig4_qr_portal.png'); print('fig4')
