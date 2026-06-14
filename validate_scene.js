#!/usr/bin/env node
/*
 * Headless validator for VisualLM scene code.
 *
 * Reads a scene body (the inside of `function scene(ctx, t) { ... }`) on stdin
 * and runs it against a BEHAVIOR-FAITHFUL mock of the worker's `H` helper
 * library + a counting 2D context, at several values of `t`. Reports JSON on
 * stdout:
 *   ok      — did the body run without throwing at every sampled frame?
 *   error   — first throw's message (null if ok)
 *   painted — did it issue any content draw call (background/clear excluded)?
 *   text    — did it draw any text (title/labels/readouts)?
 *   paint   — content draw-call count
 *
 * This lets the Python server validate (and drive repairs) WITHOUT a browser
 * round-trip — the slow part of the old loop.
 *
 * SECURITY: the scene is AI-generated, hence untrusted. It runs in a FRESH,
 * EMPTY V8 context via `vm` — no `process`, `require`, `console`, timers, or
 * dynamic `import` reach it, and NO host object is passed in (the classic
 * `obj.constructor.constructor("return process")()` escape needs a host object
 * on the prototype chain; we hand in nothing and read results back only as a
 * primitive JSON string). A hard `timeout` kills infinite loops.
 *
 * The mock mirrors the helper API SURFACE (return shapes + chaining), not the
 * pixel internals: legitimate scenes never false-fail, and genuine
 * SyntaxError/ReferenceError/TypeError throws are caught exactly as the browser
 * sandbox would catch them. Keep the method list in sync with
 * sandbox-worker.js's makeHelpers() when helpers are added.
 */
"use strict";

const vm = require("vm");

// The mock helper library, as source evaluated INSIDE the sandbox context so
// every object's prototype chain stays inside the sandbox (no host leak). No
// backticks in here — this whole thing is a template literal. `var`-declared
// names (H/ctx/cam/view/v/paint/text) persist on the context global.
const SANDBOX_SRC = `
var paint = 0, text = 0, conscr = 0;
var console = { log: function(){}, warn: function(){}, error: function(){}, info: function(){} };
var W = 900, H_ = 560, TAU = Math.PI * 2;
// On-screen test (generous margin). A draw whose points all land far outside
// the canvas is invisible — the tell-tale of mixing data and pixel coords
// (e.g. v.line(v.X(x), ...) double-transforms). 'paint' counts CONTENT draws
// (not background/grid/axes scaffold); 'conscr' counts those that land
// on-screen. paint>0 with conscr===0 means "everything was drawn off-screen".
function inb(x, y){ return typeof x === "number" && typeof y === "number" && isFinite(x) && isFinite(y) && x >= -120 && x <= W + 120 && y >= -120 && y <= H_ + 120; }
function onAny(pairs){ for (var i = 0; i < pairs.length; i++) if (inb(pairs[i][0], pairs[i][1])) return true; return false; }
function content(on){ paint++; if (on) conscr++; }
var COLORS = {
  bg:"#0e1525", panel:"#16203a", ink:"#eef2ff", sub:"#9fb0d4", grid:"#26314f",
  axis:"#566087", accent:"#7cc4ff", accent2:"#f4a259", good:"#67e8b0",
  warn:"#ff8aa0", violet:"#c4a7ff", yellow:"#ffe08a"
};
var PALETTE = ["#7cc4ff","#f4a259","#67e8b0","#c4a7ff","#ff8aa0","#ffe08a","#5eead4","#fca5f1"];
function clamp(x,lo,hi){ return x<lo?lo:x>hi?hi:x; }
function lerp(a,b,t){ return a+(b-a)*t; }
function map(x,a,b,c,d){ return b===a?c:c+((x-a)*(d-c))/(b-a); }
function ease(t){ t=clamp(t,0,1); return t*t*(3-2*t); }
function wrap(obj){
  return new Proxy(obj, { get: function(t,k){ if(k in t) return t[k]; return function(){ return undefined; }; } });
}
function makeCtx(){
  var grad = { addColorStop: function(){} };
  var PAINT = { fill:1, stroke:1, fillRect:1, strokeRect:1, fillText:1, strokeText:1, drawImage:1, putImageData:1 };
  var TEXTOP = { fillText:1, strokeText:1 };
  var target = {
    canvas: { width: W, height: H_ },
    createLinearGradient: function(){ return grad; },
    createRadialGradient: function(){ return grad; },
    createPattern: function(){ return null; },
    measureText: function(){ return { width: 8 }; },
    getImageData: function(){ return { data: [], width: 0, height: 0 }; },
    setLineDash: function(){}, getLineDash: function(){ return []; }
  };
  return new Proxy(target, {
    get: function(t,k){
      if(k in t) return t[k];
      if(typeof k !== "string") return undefined;
      return function(){ if(PAINT[k]) paint++; if(TEXTOP[k]) text++; return undefined; };
    },
    set: function(){ return true; }
  });
}
function makeH(){
  var H = {
    TAU: TAU, PI: Math.PI, colors: COLORS, palette: PALETTE,
    clamp: clamp, lerp: lerp, map: map, ease: ease, W: W, H: H_,
    clear: function(){}, background: function(){},
    text: function(s,x,y){ text++; content(inb(x,y)); },
    line: function(x1,y1,x2,y2){ content(onAny([[x1,y1],[x2,y2]])); },
    path: function(p){ if(p && p.length>=2) content(onAny(p)); },
    circle: function(x,y){ content(inb(x,y)); },
    rect: function(x,y,w,h){ content(onAny([[x,y],[x+w,y+h]])); },
    arrow: function(x1,y1,x2,y2){ content(onAny([[x1,y1],[x2,y2]])); },
    legend: function(items){ (items||[]).forEach(function(){ text++; }); content(true); },
    color: function(i){ return PALETTE[((i%PALETTE.length)+PALETTE.length)%PALETTE.length]; },
    hsl: function(h,s,l,a){ return "hsla("+h+","+s+"%,"+l+"%,"+(a==null?1:a)+")"; },
    plot2d: function(o){
      o=o||{};
      var xMin=o.xMin==null?-10:o.xMin, xMax=o.xMax==null?10:o.xMax;
      var yMin=o.yMin==null?-6:o.yMin, yMax=o.yMax==null?6:o.yMax;
      var pad=o.pad==null?46:o.pad;
      var box=o.box||{ x:pad, y:pad*0.6, w:W-pad*2, h:H_-pad*1.6 };
      var X=function(v){ return box.x+map(v,xMin,xMax,0,box.w); };
      var Y=function(v){ return box.y+map(v,yMin,yMax,box.h,0); };
      // grid/axes are scaffold (don't count as content); fn maps internally so
      // it's reliably on-screen. The data-space methods convert via X/Y then
      // check bounds, so a scene that wraps args in v.X()/v.Y() (double map)
      // shows up as off-screen content.
      var view={
        box:box, xMin:xMin, xMax:xMax, yMin:yMin, yMax:yMax, X:X, Y:Y,
        grid:function(){ return view; },
        axes:function(){ text++; return view; },
        fn:function(f){ for(var i=0;i<=12;i++){ try{ f(lerp(xMin,xMax,i/12)); }catch(e){} } content(true); return view; },
        dot:function(x,y){ content(inb(X(x),Y(y))); return view; },
        line:function(x1,y1,x2,y2){ content(onAny([[X(x1),Y(y1)],[X(x2),Y(y2)]])); return view; },
        arrow:function(x1,y1,x2,y2){ content(onAny([[X(x1),Y(y1)],[X(x2),Y(y2)]])); return view; },
        text:function(s,x,y){ text++; content(inb(X(x),Y(y))); return view; },
        circle:function(x,y){ content(inb(X(x),Y(y))); return view; },
        path:function(p){ if(p && p.length){ var q=[]; for(var i=0;i<p.length;i++) q.push([X(p[i][0]),Y(p[i][1])]); content(onAny(q)); } return view; },
        rect:function(x,y,w,h){ content(onAny([[X(x),Y(y)],[X(x+w),Y(y+h)]])); return view; }
      };
      return wrap(view);
    },
    cam3d: function(o){
      o=o||{};
      var yaw=o.yaw||0, pitch=o.pitch==null?-0.5:o.pitch;
      var scale=o.scale||60, dist=o.dist||9;
      var cx=o.cx==null?W/2:o.cx, cy=o.cy==null?H_/2:o.cy;
      function proj(p){ var x=(p&&p[0])||0,y=(p&&p[1])||0,z=(p&&p[2])||0; var f=dist/(dist+z); return { x:cx+x*scale*f, y:cy-y*scale*f, depth:z, f:f }; }
      var cam={
        get yaw(){ return yaw; }, set yaw(v){ yaw=v; },
        get pitch(){ return pitch; }, set pitch(v){ pitch=v; },
        project:proj,
        line:function(a,b){ var p1=proj(a),p2=proj(b); content(onAny([[p1.x,p1.y],[p2.x,p2.y]])); return cam; },
        path:function(p){ if(p && p.length>=2){ var q=[]; for(var i=0;i<p.length;i++){ var pr=proj(p[i]); q.push([pr.x,pr.y]); } content(onAny(q)); } return cam; },
        poly:function(p){ if(p && p.length>=3){ var q=[]; for(var i=0;i<p.length;i++){ var pr=proj(p[i]); q.push([pr.x,pr.y]); } content(onAny(q)); } return cam; },
        sphere:function(p){ var q=proj(p); content(inb(q.x,q.y)); return q; },
        grid:function(){ return cam; },
        axes:function(){ text++; return cam; }
      };
      return wrap(cam);
    },
    surface3d: function(cam,f){ if(typeof f==="function"){ for(var i=0;i<6;i++) for(var j=0;j<6;j++){ try{ f(i-3,j-3); }catch(e){} } } content(true); },
    mesh3d: function(cam,fn){ if(typeof fn==="function"){ for(var i=0;i<6;i++) for(var j=0;j<6;j++){ try{ fn((i/6)*TAU,(j/6)*TAU); }catch(e){} } } content(true); }
  };
  return wrap(H);
}
var H = makeH();
var ctx = makeCtx();
var cam = H.cam3d({});
var view = H.plot2d({});
var v = view;
`;

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => (data += c));
    process.stdin.on("end", () => resolve(data));
  });
}

(async () => {
  const code = await readStdin();
  let result = { ok: false, error: null, painted: false, text: false, paint: 0, onscreen: true };

  // The runner: define the scene as the body of a function (so a scene's own
  // `const v = ...` shadows the global v instead of colliding with a
  // parameter), call it at several frames, and RETURN a JSON string. Building
  // it with string concatenation means the scene's own backticks/quotes need
  // no escaping. A `};` injection only lands the attacker back in this same
  // empty sandbox — no escalation.
  const runner =
    SANDBOX_SRC +
    "\n;(function(){var __ok=false,__err=null;try{var __s=function(ctx,t){\n" +
    code +
    "\n};var __ts=[0,0.4,1.3,3.0];for(var __i=0;__i<__ts.length;__i++){__s(ctx,__ts[__i]);}__ok=true;}" +
    "catch(e){__ok=false;__err=(e&&e.message)?String(e.message):String(e);}" +
    "return JSON.stringify({ok:__ok,error:__err,paint:paint,text:text,conscr:conscr});})()";

  try {
    const context = vm.createContext(Object.create(null));
    const out = vm.runInContext(runner, context, { timeout: 2000 });
    const parsed = JSON.parse(out);
    result.ok = !!parsed.ok;
    result.error = parsed.error || null;
    result.paint = parsed.paint || 0;
    result.painted = (parsed.paint || 0) > 0;
    result.text = (parsed.text || 0) > 0;
    // Content was drawn, but none of it landed on the canvas → the scene is
    // effectively blank (almost always a data-vs-pixel coordinate mixup).
    result.onscreen = !((parsed.paint || 0) > 0 && (parsed.conscr || 0) === 0);
  } catch (err) {
    const msg = err && err.message ? String(err.message) : String(err);
    if (/timed out|execution timed/i.test(msg)) {
      result.error = "The scene hung (possible infinite loop).";
    } else {
      result.error = msg; // SyntaxError etc. — compile failed before running
    }
  }
  process.stdout.write(JSON.stringify(result));
})();
