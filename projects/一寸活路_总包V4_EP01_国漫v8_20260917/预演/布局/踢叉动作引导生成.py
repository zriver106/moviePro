# 仅生成局部动作引导，禁止作为交付素材或剧情补时。
import cv2,numpy as np,pathlib
p=pathlib.Path('/Users/andy/moviePro/projects/一寸活路_总包V4_EP01_国漫v8_20260917');t=cv2.imread(str(p/'参考/S14靴尖同尺寸.png'));orig=cv2.imread(str(p/'参考/S14原片1秒.png'));h,w=t.shape[:2]
poly=np.array([(330,378),(365,383),(376,425),(362,459),(343,493),(347,539),(362,585),(364,603),(350,619),(320,631),(280,629),(266,615),(271,601),(291,592),(307,587),(307,552),(298,516),(288,480),(272,455),(267,426),(270,406),(290,388)],np.int32)
lm=np.zeros((h,w),np.uint8);cv2.fillPoly(lm,[poly],255);lm=cv2.GaussianBlur(lm,(5,5),.8);base=cv2.inpaint(t,lm,5,cv2.INPAINT_TELEA);al=lm[:,:,None]/255;base[460:]=(t[460:]*(1-al[460:])+orig[460:]*al[460:]).astype('uint8')
fm=np.zeros((h,w),np.uint8);fp=np.array([(212,555),(216,557),(223,573),(235,581),(244,585),(248,595),(480,790),(480,819),(237,609),(232,604),(218,608),(204,605),(192,597),(178,582),(176,572),(183,574),(196,589),(208,594),(219,595),(229,590),(225,582),(219,578)],np.int32);cv2.fillPoly(fm,[fp],255);erase=cv2.dilate(fm,np.ones((13,13),np.uint8));cv2.rectangle(erase,(170,545),(268,645),255,-1);base=cv2.inpaint(base,erase,5,cv2.INPAINT_TELEA);fork=orig.astype('float32')*fm[:,:,None]/255;leg=t.astype('float32')*lm[:,:,None]/255
xs=[250,285,320,355,390];ys=[370,410,450,490,530,570,640];src=np.array([(x,y) for y in ys for x in xs],np.float32);tri=[]
for j in range(len(ys)-1):
 for k in range(len(xs)-1):
  q=j*len(xs)+k;tri.extend([(q,q+1,q+len(xs)),(q+1,q+len(xs)+1,q+len(xs))])
v=cv2.VideoWriter(str(p/'预演/布局/S14同机位局部踢叉动作引导_v04.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),24,(480,854))
for i in range(96):
 sec=i/24;angle=-40 if sec<.5 else (-40+80*(sec-.5) if sec<1 else -25*min(1,(sec-1)/.35));r=np.deg2rad(angle)*np.clip((src[:,1]-380)/220,0,1);d=src-np.array([330,410]);dst=np.column_stack([d[:,0]*np.cos(r)-d[:,1]*np.sin(r),d[:,0]*np.sin(r)+d[:,1]*np.cos(r)])+np.array([330,410]);dst[:,1]+=18*np.clip((src[:,1]-450)/180,0,1);dst=dst.astype('float32');la=np.zeros((h,w),np.float32);lp=np.zeros((h,w,3),np.float32);weight=np.zeros((h,w),np.float32)
 for ids in tri:
  ss=src[list(ids)];dd=dst[list(ids)];M=cv2.getAffineTransform(ss,dd);mask=np.zeros((h,w),np.float32);cv2.fillConvexPoly(mask,np.round(dd).astype('int32'),1);lp+=cv2.warpAffine(leg,M,(w,h))*mask[:,:,None];la+=cv2.warpAffine(lm.astype('float32')/255,M,(w,h))*mask;weight+=mask
 weight=np.maximum(weight,1);la=(la/weight).clip(0,1);lp=(lp/weight[:,:,None]).clip(0,255);k=np.clip((sec-1)/.35,0,1);M=np.float32([[1,0,180*k],[0,1,160*k]]);fa=cv2.warpAffine(fm.astype('float32')/255,M,(w,h));ff=cv2.warpAffine(fork,M,(w,h));fr=base*(1-fa[:,:,None])+ff;fr=fr*(1-la[:,:,None])+lp;fr=fr.clip(0,255).astype('uint8');v.write(fr)
 if i in [12,24,30]:cv2.imwrite(str(p/f'预演/布局/S14引导v04_{i}.png'),fr)
v.release()
