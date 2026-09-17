"""S14动作布局示意：供原片编辑参考，不作为剧情画面或成片。"""
from pathlib import Path
import math, subprocess
import numpy as np
import cv2

P=Path(__file__).resolve().parents[1]/'projects/一寸活路_总包V4_EP01_国漫v8_20260917'
OUT=P/'预演/布局/S14动作接触示意.mp4'
W,H,FPS=576,1024,24
BLUE=(174,116,65); BROWN=(55,120,175); SKIN=(158,188,211)
def blend(a,b,u):return np.array(a)*(1-u)+np.array(b)*u
def ramp(t,a,b):
    u=max(0,min(1,(t-a)/(b-a)));return u*u*(3-2*u)
def project(p):
    x,y,z=p
    return (int(288+x*157),int(695-y*72-z*157))
def depth(p):return p[1]-.6*p[2]
def frame(t):
    im=np.full((H,W,3),(205,215,218),np.uint8);shapes=[]
    def line(a,b,r,c):shapes.append((sum(map(depth,[a,b]))/2,'line',a,b,r,c))
    def dot(a,r,c):shapes.append((depth(a),'dot',a,a,r,c))
    def chain(points,r,c):
        for a,b in zip(points,points[1:]):line(a,b,r,c)
    def ring(center,r,plane,c,portion=1):
        pts=[]
        for u in np.linspace(0,2*math.pi*portion,max(2,int(48*portion))):
            q=np.array(center,dtype=float);q[plane[0]]+=r*math.cos(u);q[plane[1]]+=r*math.sin(u);pts.append(q)
        chain(pts,.014,c)
    for x in np.arange(-2,2.1,.5):cv2.line(im,project((x,-2,0)),project((x,2,0)),(178,190,190),1)
    for y in np.arange(-2,2.1,.5):cv2.line(im,project((-2,y,0)),project((2,y,0)),(178,190,190),1)
    # The same tall post receives the wrist restraint.
    line((-1.5,.15,0),(-1.5,.15,1.65),.075,(70,100,125))
    line((-1.65,.15,1.45),(-1.3,.15,1.45),.055,(70,100,125))
    line((-1.58,.15,.85),(-1.40,.15,.85),.035,(60,85,110))
    # Supine stocky adult: separate shoulders, elbows, wrists and booted legs.
    line((-.68,0,.24),(.35,0,.18),.23,BROWN);dot((-.99,0,.29),.16,SKIN)
    for y in [-.11,.11]:
        chain([(.3,y,.18),(.75,y,.13),(1.14,y,.09)],.075,(52,53,57))
        line((1.12,y,.09),(1.35,y,.13),.08,(27,29,31))
    ring((1.08,0,.10),.19,(1,2),(120,175,214))
    gather=ramp(t,3.35,5.05)
    wrists=[]
    for y in [-.48,.48]:
        wrist=blend((-.35,y,.08),(-1.26,(-.055 if y<0 else .08),.62),gather)
        elbow=blend((-.5,y,.19),(-.63,y*.8,.32),gather)
        if 8.55<t<9.15:elbow[1]+=.07*math.sin((t-8.55)/.6*math.pi)
        shoulder=(-.62,math.copysign(.2,y),.26)
        chain([shoulder,elbow],.073,BROWN);chain([elbow,wrist],.053,SKIN);dot(wrist,.065,SKIN)
        wrists.append(wrist)
    # Blue adult keeps one knee on the chest; the other leg performs the kick.
    hip=(.12,-.56,.56);shoulder=(-.39,-.50,1.13)
    line(hip,shoulder,.16,BLUE);dot((-.49,-.48,1.43),.13,SKIN)
    chest_knee=(-.46,-.12,.41)
    chain([hip,chest_knee,(-.12,-.1,.22)],.085,(53,54,60))
    kick=ramp(t,.75,1.25)*(1-ramp(t,1.4,1.95))
    boot=blend((.65,-.73,.08),(.70,-1.4,.09),kick)
    chain([hip,(.45,-.78,.38),boot],.085,(53,54,60));dot(boot,.10,(28,29,31))
    left_hand=wrists[0]
    chain([(-.5,-.61,1.04),(-.70,-.57,.68),left_hand],.048,SKIN)
    if t<2:right_hand=(-.2,-.6,.82)
    elif t<3.3:right_hand=blend((-.2,-.6,.82),(-1.49,.13,1.12),ramp(t,2,3.1))
    elif t<5.05:right_hand=blend((-1.49,.13,1.12),wrists[1],ramp(t,3.3,4.4))
    elif t<7:right_hand=(-1.26,.02,.65)
    else:right_hand=blend((-1.26,.02,.65),(-1.46,.1,.85),ramp(t,7,8.3))
    chain([(-.3,-.4,1.05),(-.7,-.38,.90),right_hand],.048,SKIN)
    # One complete fork slides after visible boot contact.
    fy=-1.03-.8*ramp(t,1.0,1.5)
    line((-.1,fy,.06),(1.25,fy,.06),.027,(65,98,124))
    chain([(-.1,fy-.1,.06),(-.27,fy-.1,.06),(-.27,fy+.1,.06),(-.1,fy+.1,.06)],.018,(34,37,39))
    if t<3.15:ring((-1.50,.12,1.14),.12,(0,2),(120,175,214))
    elif t<4.3:
        ring(right_hand,.145,(1,2),(120,175,214))
        chain([right_hand,np.array(right_hand)+(0,0,-.25)],.014,(120,175,214))
    if t>=4.3:
        ring((-1.26,.0125,.62),.145,(1,2),(120,175,214),ramp(t,4.3,5.8))
    if t>=5.8:
        chain([(-1.26,.15,.62),(-1.5,.25,.62)],.014,(120,175,214))
        ring((-1.5,.15,.62),.105,(0,1),(120,175,214),ramp(t,5.8,7.2))
    if t>=7.2:chain([(-1.5,.045,.62),(-1.46,.1,.85)],.014,(120,175,214))
    for _,kind,a,b,r,c in sorted(shapes,key=lambda s:s[0],reverse=True):
        pa,pb=project(a),project(b);rr=max(2,int(r*157))
        if kind=='line':cv2.line(im,pa,pb,c,rr*2,cv2.LINE_AA)
        cv2.circle(im,pa,rr,c,-1,cv2.LINE_AA);cv2.circle(im,pb,rr,c,-1,cv2.LINE_AA)
    return im
if __name__=='__main__':
    OUT.parent.mkdir(parents=True,exist_ok=True)
    ff=subprocess.Popen(['/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-pix_fmt','yuv420p','-crf','17',str(OUT)],stdin=subprocess.PIPE)
    for i in range(10*FPS):ff.stdin.write(frame(i/FPS).tobytes())
    ff.stdin.close();assert ff.wait()==0
    for t in [1,4,6,9]:cv2.imwrite(str(OUT.with_name(f'S14示意_{t}s.png')),frame(t))
    print(OUT)
