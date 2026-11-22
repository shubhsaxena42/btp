import sys, io
from playwright.sync_api import sync_playwright
from PIL import Image, ImageOps
B='http://127.0.0.1:5050'; W,H=1840,880
BATCH=107; SALE=23

def fit(png, out, anchor_top=True):
    im=Image.open(io.BytesIO(png)).convert('RGB')
    w,h=im.size; r=W/H
    if w/h > r:   # too wide -> pad height
        nh=int(w/r); c=Image.new('RGB',(w,nh),'white'); c.paste(im,(0,(nh-h)//2)); im=c
    elif w/h < r: # too tall -> pad width
        nw=int(h*r); c=Image.new('RGB',(nw,h),'white'); c.paste(im,((nw-w)//2,0)); im=c
    im=im.resize((W,H),Image.LANCZOS); im.save(out); print(out, im.size)

with sync_playwright() as p:
    br=p.chromium.launch()
    ctx=br.new_context(viewport={'width':1440,'height':900},device_scale_factor=2)
    ctx.add_init_script('window.print=function(){};')
    pg=ctx.new_page(); pg.goto(B+'/lang/en'); pg.wait_for_load_state('networkidle')
    # fig1 dashboard: main content only (no footer)
    pg.goto(B+'/'); pg.wait_for_load_state('networkidle')
    foot=pg.locator('footer').first.bounding_box()
    top_h = foot['y'] if foot else 1700
    h=min(top_h, 1440*H/W*1.0+400)
    # choose clip height: aim close to ratio but include KPIs+chart+alerts
    clip_h=min(top_h, 1440/ (W/H) * 1.6)
    open('/tmp/_dash_h.txt','w').write(str((top_h,clip_h)))
    fit(pg.screenshot(clip={'x':0,'y':0,'width':1440,'height':clip_h}), 'shots/fig1_dashboard.png')
    # fig2 batch
    pg.goto(B+f'/batches/{BATCH}'); pg.wait_for_load_state('networkidle')
    pg.screenshot(path='shots/_fig2_full.png', full_page=True)
    # fig3 invoice
    pg.goto(B+f'/sales/{SALE}/print'); pg.wait_for_load_state('networkidle')
    pg.screenshot(path='shots/_fig3_full.png', full_page=True)
    # QR label popup
    pg.goto(B+f'/batches/{BATCH}'); pg.wait_for_load_state('networkidle')
    verify=pg.locator('#qr-label a').get_attribute('href'); print('VERIFY', verify)
    with ctx.expect_page() as pi: pg.click('#print-qr')
    pop=pi.value; pop.set_viewport_size({'width':420,'height':560}); pop.wait_for_load_state('networkidle'); pop.wait_for_timeout(500)
    pop.screenshot(path='shots/_label.png', full_page=True)
    # phone portal
    m=br.new_context(viewport={'width':390,'height':844},device_scale_factor=3,is_mobile=True,has_touch=True)
    mp=m.new_page(); mp.goto(verify); mp.wait_for_load_state('networkidle'); mp.wait_for_timeout(2500)
    mp.screenshot(path='shots/_portal.png')
    br.close()
