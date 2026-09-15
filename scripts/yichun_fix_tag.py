#!/usr/bin/env python3
"""现有视频牌面文字局部合成与特写放大，原视频及声音保留。"""
import json
import subprocess
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from yichun_video30 import P,K,sha,write,require_plan

ROOT=K/'延长试验/EP001/牌面修复_v1'
SOURCE=K/'延长试验/EP001/一寸活路_第一集_30秒延长至60秒_中文字幕.mp4'
FONT='/System/Library/Fonts/STHeiti Medium.ttc'

def layers(frame):
    # 所有坐标来自本次原片实际牌面，原刻字区域不覆盖手指。
    erase=np.zeros(frame.shape[:2],np.uint8)
    cv2.fillPoly(erase,[np.array([[408,325],[500,319],[511,373],[406,382]],np.int32)],255)
    texture=cv2.warpAffine(frame,np.float32([[1,0,145],[0,1,0]]),(854,480))
    blend=cv2.GaussianBlur(erase.astype(float)/255,(5,5),.7)[:,:,None]
    clean=(frame*(1-blend)+texture*blend).astype('uint8')
    layer=Image.new('RGBA',(854,480));d=ImageDraw.Draw(layer)
    for text,size,xy in [('陆照',24,(394,322)),('溺亡销籍',22,(371,345)),('登记于六个月前',16,(351,366))]:
        d.text(xy,text,font=ImageFont.truetype(FONT,size),fill=(43,24,13,255))
    overlay=np.asarray(layer).copy()
    alpha=overlay[:,:,3:4].astype(float)/255
    out=(cv2.cvtColor(clean,cv2.COLOR_BGR2RGB)*(1-alpha)+overlay[:,:,:3]*alpha).astype('uint8')
    return cv2.cvtColor(out,cv2.COLOR_RGB2BGR),np.maximum(blend[:,:,0],alpha[:,:,0])

def main():
    require_plan();ROOT.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((SOURCE.parent/'输出清单.json').read_text())
    if sha(SOURCE)!=manifest['sha256']:raise ValueError('待修原片指纹与输出记录不符')
    cap=cv2.VideoCapture(str(SOURCE));ok,first=cap.read();assert ok
    base_gray=cv2.cvtColor(first,cv2.COLOR_BGR2GRAY)
    feature_mask=np.zeros((480,854),np.uint8)
    cv2.fillPoly(feature_mask,[np.array([[235,329],[575,328],[583,365],[236,389]],np.int32)],255)
    pts=cv2.goodFeaturesToTrack(base_gray,150,.01,4,mask=feature_mask)
    fixed,base_alpha=layers(first)
    fps=cap.get(cv2.CAP_PROP_FPS);count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));cap.set(cv2.CAP_PROP_POS_FRAMES,0)
    output=ROOT/'一寸活路_第一集60秒_牌面字放大.mp4'
    command=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s','854x480','-r',str(fps),'-i','pipe:0','-i',str(SOURCE),'-map','0:v','-map','1:a:0','-c:v','libx264','-crf','16','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(output)]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE)
    tracks=[]
    for n in range(count):
        ok,frame=cap.read();assert ok
        if n<65:
            gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            cur,status,err=cv2.calcOpticalFlowPyrLK(base_gray,gray,pts,None,winSize=(21,21),maxLevel=3)
            good=(status.ravel()==1)&(err.ravel()<15)
            matrix,inliers=cv2.estimateAffinePartial2D(pts[good],cur[good],method=cv2.RANSAC,ransacReprojThreshold=2)
            if matrix is None:raise ValueError(f'牌面跟踪失败: {n}')
            warped=cv2.warpAffine(fixed,matrix,(854,480))
            alpha=cv2.warpAffine(base_alpha.astype(np.float32),matrix,(854,480))
            rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB).astype(float);r,g,b=rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
            skin=((r>g*1.12)&((g-b)<.28*(r-b))&(r>100)).astype('uint8')
            skin=cv2.morphologyEx(skin,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
            total,labels,stats,_=cv2.connectedComponentsWithStats(skin)
            hand=np.zeros_like(skin)
            for label in range(1,total):
                if stats[label,cv2.CC_STAT_AREA]>1500:hand[labels==label]=1
            hand=cv2.dilate(hand,np.ones((5,5),np.uint8));alpha[hand>0]=0
            frame=np.clip(frame*(1-alpha[:,:,None])+warped*alpha[:,:,None],0,255).astype('uint8')
            tracks.append({'frame':n,'inliers':int(inliers.sum()),'matrix':matrix.tolist()})
        if n<68:
            frame=cv2.resize(frame[228:430,292:652],(854,480),interpolation=cv2.INTER_LANCZOS4)
        if n in [0,24,48,60,61,62,63,64,65,67,68,72]:cv2.imwrite(str(ROOT/f'check_{n:03}.png'),frame)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait()!=0:raise RuntimeError('视频导出失败')
    write(ROOT/'修复记录.json',{'source':str(SOURCE.relative_to(P)),'source_sha256':sha(SOURCE),'output':str(output.relative_to(P)),'output_sha256':sha(output),'method':'局部牌面刻字清理、跟踪合成、开头特写放大约2.37倍；本机后期，无模型生成调用','text':'陆照\n溺亡销籍\n登记于六个月前','edited_frames':list(range(68)),'audio':'原音轨直接复制','bgm_added':False,'tracks':tracks,'status':'pending_visual_check'})
    print(output)

if __name__=='__main__':main()
