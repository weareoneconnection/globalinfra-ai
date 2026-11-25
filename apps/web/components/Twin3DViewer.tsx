'use client';

import { useEffect, useRef, useState } from 'react';
import type { TwinObject } from './TwinWorkspace';

type Node3D={twinId:string;name:string;elementType:string;translation:number[];scale:number[];rotation:number;health:number;progress:number;cost:number};
type Mode='health'|'progress'|'cost';
type GltfNode={name?:unknown;mesh?:unknown;translation?:unknown;scale?:unknown;rotation?:unknown;extras?:unknown};

const VERTICES=new Float32Array([
  -1,-1,-1, 1,-1,-1, 1,1,-1, -1,-1,-1, 1,1,-1,-1,1,-1,
  -1,-1,1, 1,1,1, 1,-1,1, -1,-1,1,-1,1,1, 1,1,1,
  -1,-1,-1,-1,1,-1,-1,1,1, -1,-1,-1,-1,1,1,-1,-1,1,
  1,-1,-1,1,-1,1,1,1,1, 1,-1,-1,1,1,1,1,1,-1,
  -1,1,-1,1,1,-1,1,1,1, -1,1,-1,1,1,1,-1,1,1,
  -1,-1,-1,1,-1,1,1,-1,-1, -1,-1,-1,-1,-1,1,1,-1,1
]);
const VS=`attribute vec3 p;uniform mat4 m;uniform mat4 vp;void main(){gl_Position=vp*m*vec4(p,1.0);}`;
const FS=`precision mediump float;uniform vec3 c;void main(){float shade=.72+gl_FragCoord.y*.00035;gl_FragColor=vec4(c*shade,1.0);}`;
const mul=(a:Float32Array,b:Float32Array)=>{const o=new Float32Array(16);for(let r=0;r<4;r++)for(let c=0;c<4;c++)for(let k=0;k<4;k++)o[c*4+r]+=a[k*4+r]*b[c*4+k];return o};
const perspective=(f:number,a:number,n:number,far:number)=>{const t=1/Math.tan(f/2),o=new Float32Array(16);o[0]=t/a;o[5]=t;o[10]=(far+n)/(n-far);o[11]=-1;o[14]=2*far*n/(n-far);return o};
const transform=(x:number,y:number,z:number,sx:number,sy:number,sz:number,ry=0)=>new Float32Array([Math.cos(ry)*sx,0,-Math.sin(ry)*sx,0, 0,sy,0,0, Math.sin(ry)*sz,0,Math.cos(ry)*sz,0, x,y,z,1]);
const color=(node:Node3D,mode:Mode):[number,number,number]=>{const score=mode==='health'?node.health:mode==='progress'?node.progress:Math.max(0,100-node.cost);return score<70?[.94,.29,.31]:score<85?[1,.66,.25]:[.18,.82,.72]};
const draftColor=(type:string):[number,number,number]=>({WALL:[.24,.62,.72],DOOR:[.86,.58,.20],SPACE:[.25,.70,.52],EQUIPMENT:[.58,.42,.82]}[type] as [number,number,number]|undefined)??[.45,.58,.70];
const fitNodes=(input:Node3D[]):Node3D[]=>{if(!input.length)return input;const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];input.forEach(node=>node.translation.forEach((value,index)=>{const half=Math.abs(node.scale[index]??1)/2;min[index]=Math.min(min[index],value-half);max[index]=Math.max(max[index],value+half)}));const center=min.map((value,index)=>(value+max[index])/2),span=Math.max(1,...max.map((value,index)=>value-min[index])),factor=8/span;return input.map(node=>({...node,translation:node.translation.map((value,index)=>(value-center[index])*factor),scale:node.scale.map(value=>Math.max(.02,Math.abs(value)*factor/2))}))};
const isRecord=(value:unknown):value is Record<string,unknown>=>Boolean(value)&&typeof value==='object'&&!Array.isArray(value);
const vector=(value:unknown,length:number,positive=false):number[]|null=>Array.isArray(value)&&value.length===length&&value.every(item=>typeof item==='number'&&Number.isFinite(item)&&(!positive||item>0))?value:null;

function parseGltf(gltf:unknown,objects:TwinObject[]):Node3D[]{
  if(!isRecord(gltf)||!isRecord(gltf.asset)||gltf.asset.version!=='2.0')throw new Error('Invalid glTF package');
  const rawNodes=gltf.nodes,rawMeshes=gltf.meshes;
  if(!Array.isArray(rawNodes)||!Array.isArray(rawMeshes)||!rawMeshes.length||!rawNodes.length||rawNodes.length!==objects.length)throw new Error('Invalid glTF package');
  const objectById=new Map(objects.map(object=>[object.id,object]));
  if(objectById.size!==objects.length)throw new Error('Duplicate response Twin IDs');
  const seen=new Set<string>();
  const parsed=rawNodes.map((raw,index)=>{
    if(!isRecord(raw))throw new Error(`Invalid glTF node ${index}`);
    const node=raw as GltfNode,extras=isRecord(node.extras)?node.extras:{};
    const twinId=typeof extras.twin_id==='string'?extras.twin_id:'';
    const twin=objectById.get(twinId);
    const translation=vector(node.translation,3),scale=vector(node.scale,3,true);
    const quaternion=node.rotation===undefined?[0,0,0,1]:vector(node.rotation,4);
    if(!twinId||!twin||seen.has(twinId)||!Number.isInteger(node.mesh)||Number(node.mesh)<0||Number(node.mesh)>=rawMeshes.length||!translation||!scale||!quaternion||Math.hypot(...quaternion)<.000001)throw new Error(`Untrusted glTF node ${index}`);
    seen.add(twinId);
    return {twinId,name:typeof node.name==='string'&&node.name.trim()?node.name:twin.name,elementType:typeof extras.element_type==='string'?extras.element_type:twin.object_type,translation,scale,rotation:2*Math.atan2(quaternion[1],quaternion[3]),health:typeof extras.health==='number'&&Number.isFinite(extras.health)?extras.health:twin.health_score,progress:twin.progress,cost:Number(twin.properties.costExposure??Math.max(0,100-twin.health_score))};
  });
  if(seen.size!==objectById.size)throw new Error('glTF and manifest objects differ');
  return fitNodes(parsed);
}

export function Twin3DViewer({url,objects,onSelect,draftMode=false}:{url:string;objects:TwinObject[];onSelect:(id:string)=>void;draftMode?:boolean}){
  const canvasRef=useRef<HTMLCanvasElement>(null);
  const [nodes,setNodes]=useState<Node3D[]>([]); const [mode,setMode]=useState<Mode>('health'); const [timeline,setTimeline]=useState(100); const [status,setStatus]=useState('LOADING GLTF'); const [selected,setSelected]=useState('');
  useEffect(()=>{let active=true;setStatus('LOADING GLTF');setNodes([]);fetch(url,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error();return r.json()}).then(gltf=>{if(!active)return;const parsed=parseGltf(gltf,objects);setNodes(parsed);setStatus(`GLTF 2.0 · ${parsed.length} OBJECTS`)}).catch(()=>{if(!active)return;setNodes([]);setStatus('ARTIFACT PREVIEW FAILED')});return()=>{active=false}},[url,objects]);
  useEffect(()=>{
    const canvas=canvasRef.current;
    if(!canvas||!nodes.length)return;
    const gl=canvas.getContext('webgl',{antialias:true,alpha:false});
    if(!gl){setStatus('WEBGL UNAVAILABLE');return}
    const compile=(type:number,source:string)=>{const shader=gl.createShader(type);if(!shader)return null;gl.shaderSource(shader,source);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){gl.deleteShader(shader);return null}return shader};
    const vertex=compile(gl.VERTEX_SHADER,VS),fragment=compile(gl.FRAGMENT_SHADER,FS);
    const program=vertex&&fragment?gl.createProgram():null;
    if(!vertex||!fragment||!program){if(vertex)gl.deleteShader(vertex);if(fragment)gl.deleteShader(fragment);setStatus('WEBGL RENDER FAILED');return}
    gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);gl.deleteShader(vertex);gl.deleteShader(fragment);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS)){gl.deleteProgram(program);setStatus('WEBGL RENDER FAILED');return}
    gl.useProgram(program);
    const buffer=gl.createBuffer(),p=gl.getAttribLocation(program,'p'),um=gl.getUniformLocation(program,'m'),uvp=gl.getUniformLocation(program,'vp'),uc=gl.getUniformLocation(program,'c');
    if(!buffer||p<0||!um||!uvp||!uc){if(buffer)gl.deleteBuffer(buffer);gl.deleteProgram(program);setStatus('WEBGL RENDER FAILED');return}
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,VERTICES,gl.STATIC_DRAW);gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,3,gl.FLOAT,false,0,0);gl.enable(gl.DEPTH_TEST);
    let frame=0,angle=-.42;
    const draw=()=>{const dpr=Math.min(devicePixelRatio,2),w=Math.max(1,canvas.clientWidth*dpr),h=Math.max(1,canvas.clientHeight*dpr);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}gl.viewport(0,0,w,h);gl.clearColor(.015,.055,.075,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);angle+=.0015;const projection=perspective(.72,w/h,.1,100);const view=transform(0,-.4,-Math.max(11,nodes.length*1.7),1,1,1,angle);gl.uniformMatrix4fv(uvp,false,mul(projection,view));nodes.forEach(node=>{if(!draftMode&&node.progress>timeline)return;const [x,y,z]=node.translation,[sx,sy,sz]=node.scale;gl.uniformMatrix4fv(um,false,transform(x*.78,y,z,sx,sy,sz,node.rotation));const c=draftMode?draftColor(node.elementType):color(node,mode);if(selected===node.twinId)c.splice(0,3,0.25,0.88,1);gl.uniform3fv(uc,c);gl.drawArrays(gl.TRIANGLES,0,36)});frame=requestAnimationFrame(draw)};
    draw();
    return()=>{cancelAnimationFrame(frame);gl.deleteBuffer(buffer);gl.deleteProgram(program)};
  },[nodes,mode,timeline,selected,draftMode]);
  return <div className={`webgl-twin ${draftMode?'draft':''}`}><div className="webgl-toolbar"><span><i className="live-dot"/>{status}</span>{draftMode?<b>DRAFT GEOMETRY</b>:<div role="group" aria-label="3D color mode">{(['health','progress','cost'] as Mode[]).map(item=><button className={mode===item?'active':''} onClick={()=>setMode(item)} key={item}>{item.toUpperCase()}</button>)}</div>}</div><div className="webgl-stage"><canvas ref={canvasRef} aria-label="Interactive WebGL digital twin preview"/><div className="webgl-grid"/><span className="webgl-hint">SELECT OBJECT BELOW · EVIDENCE LINKED</span></div>{draftMode?null:<label className="twin-timeline"><span>4D TIME</span><input aria-label="4D construction progress" type="range" min="0" max="100" value={timeline} onChange={e=>setTimeline(Number(e.target.value))}/><b>{timeline}%</b><em>5D COLOR · {mode.toUpperCase()}</em></label>}<div className="webgl-objects">{nodes.map(node=><button className={selected===node.twinId?'active':''} onClick={()=>{setSelected(node.twinId);onSelect(node.twinId)}} key={node.twinId}><span>{node.name}</span><small>{node.twinId}</small></button>)}</div></div>;
}
