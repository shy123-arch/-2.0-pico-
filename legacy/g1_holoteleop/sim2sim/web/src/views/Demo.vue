<template>
  <div id="mujoco-container"></div>
  <div class="global-alerts">
    <v-alert v-if="isSmallScreen" v-model="showSmallScreenAlert" type="warning" variant="flat" density="compact" closable class="small-screen-alert">
      Screen too small. The control panel is unavailable on small screens. Please use a desktop device.
    </v-alert>
    <v-alert v-if="isSafari" v-model="showSafariAlert" type="warning" variant="flat" density="compact" closable class="safari-alert">
      Safari has lower memory limits, which can cause WASM to crash.
    </v-alert>
  </div>
  <div v-if="!isSmallScreen" class="controls">
    <v-card class="controls-card">
      <v-card-title>G1 Tracking Demo</v-card-title>
      <v-card-text class="py-0 controls-body">
        <v-btn href="https://github.com/honglei-lab/HoloTeleop" target="_blank" variant="text" size="small" color="primary" class="text-capitalize">
          <v-icon icon="mdi-github" class="mr-1"></v-icon>Demo Code
        </v-btn>
        <v-btn href="https://github.com/honglei-lab/HoloTeleop" target="_blank" variant="text" size="small" color="primary" class="text-capitalize">
          <v-icon icon="mdi-github" class="mr-1"></v-icon>Training Code
        </v-btn>
        <v-divider class="my-2"/>

        <div class="d-flex align-center mb-1">
          <span class="status-name flex-grow-1">Bridge</span>
          <v-icon size="14" :color="bridgeConnected ? 'success' : 'grey'" class="mr-1">mdi-circle</v-icon>
          <span class="text-caption" :class="bridgeConnected ? 'text-success' : 'text-disabled'">{{ bridgeConnected ? 'online' : 'offline' }}</span>
        </div>

        <div class="d-flex align-center mt-1">
          <v-checkbox v-model="autoReturnDefault" label="Auto-return" density="compact" hide-details class="flex-grow-1"></v-checkbox>
          <v-checkbox v-model="cameraFollowEnabled" label="Cam follow" density="compact" hide-details :disabled="state !== 1" @update:modelValue="toggleCameraFollow" class="flex-grow-1"></v-checkbox>
        </div>

        <!-- Load -->
        <div class="d-flex align-center mt-2 mb-1">
          <span class="status-name flex-grow-1">Load</span>
          <v-btn icon size="x-small" variant="text" @click="refreshLoadFileList" :disabled="state !== 1"><v-icon size="16">mdi-refresh</v-icon></v-btn>
        </div>
        <div class="load-section">
          <v-select v-model="selectedFolderFilter" :items="folderFilterOptions" item-title="title" item-value="value" density="compact" hide-details placeholder="Folder" :disabled="effectiveFileList.length === 0" class="load-folder-select"></v-select>
          <div class="d-flex align-center gap-1 mt-1">
            <v-select v-model="selectedFile" :items="fileListItems" item-title="name" item-value="name" density="compact" hide-details placeholder="Select file" :disabled="effectiveFileList.length === 0 || state !== 1" :no-data-text="selectedFolderFilter ? 'No files' : 'No files (click refresh)'" @update:modelValue="onFileSelect" class="flex-grow-1">
              <template #item="{ item, props }">
                <v-list-item v-bind="props" density="compact">
                  <template #append><v-chip size="x-small" :color="folderChipColor(item.raw.folder)" variant="tonal">{{ folderChipLabel(item.raw.folder) }}</v-chip></template>
                </v-list-item>
              </template>
            </v-select>
            <v-btn color="secondary" size="small" icon variant="flat" :disabled="!selectedFile || state !== 1" @click="onLoadFileClick" title="Load"><v-icon>mdi-folder-open</v-icon></v-btn>
          </div>
          <v-btn v-if="!bridgeConnected && effectiveFileList.length === 0" block variant="tonal" color="primary" size="small" class="mt-2" :disabled="state !== 1" @click="triggerLoadNpzInput">
            <v-icon start size="18">mdi-file-upload</v-icon>Load .npz from file
          </v-btn>
          <input ref="loadNpzInput" type="file" accept=".npz" multiple class="d-none" @change="onLoadNpzFromFile">
        </div>

        <v-divider class="my-2"/>
        <span class="status-name">Policy</span>
        <div v-if="policyDescription" class="text-caption">{{ policyDescription }}</div>
        <v-select v-model="currentPolicy" :items="policyItems" class="mt-2" label="Select policy" density="compact" hide-details item-title="title" item-value="value" :disabled="isPolicyLoading || state !== 1" @update:modelValue="onPolicyChange"></v-select>
        <v-progress-linear v-if="isPolicyLoading" indeterminate height="4" color="primary" class="mt-2"></v-progress-linear>
        <v-alert v-if="policyLoadError" type="error" variant="tonal" density="compact" class="mt-2">{{ policyLoadError }}</v-alert>

        <v-divider class="my-2"/>
        <div class="status-legend follow-controls">
          <span class="status-name">Compliance</span>
          <v-btn size="x-small" variant="tonal" color="primary" :disabled="state !== 1" @click="toggleCompliance">{{ complianceEnabled ? 'On' : 'Off' }}</v-btn>
          <span class="status-name">threshold</span>
          <span class="text-caption">{{ complianceThresholdLabel }}</span>
        </div>
        <v-slider v-model="complianceThreshold" min="10" max="20" step="0.1" density="compact" hide-details :disabled="state !== 1 || !complianceEnabled" @update:modelValue="onComplianceThresholdChange"></v-slider>

        <v-divider class="my-2"/>
        <div class="motion-status" v-if="trackingState">
          <div class="status-legend" v-if="trackingState.available"><span class="status-name">Current: {{ trackingState.currentName }}</span></div>
        </div>
        <v-progress-linear v-if="shouldShowProgress" :model-value="progressValue" height="5" color="primary" rounded class="mt-3 motion-progress-no-animation"></v-progress-linear>
        <v-alert v-if="showBackToDefault" type="info" variant="tonal" density="compact" class="mt-3">
          Motion "{{ trackingState.currentName }}" finished.
          <v-btn color="primary" block density="compact" @click="backToDefault">Back to default pose</v-btn>
        </v-alert>
        <v-alert v-else-if="showMotionLockedNotice" type="warning" variant="tonal" density="compact" class="mt-3">
          "{{ trackingState.currentName }}" still playing. Wait for it to finish.
        </v-alert>

        <div v-if="showMotionSelect" class="motion-groups">
          <div v-for="group in motionGroups" :key="group.title" class="motion-group">
            <span class="status-name motion-group-title">{{ group.title }}</span>
            <v-chip v-for="item in group.items" :key="item.value" :disabled="item.disabled" :color="currentMotion === item.value ? 'primary' : undefined" :variant="currentMotion === item.value ? 'flat' : 'tonal'" class="motion-chip" size="x-small" @click="onMotionChange(item.value)">{{ item.title }}</v-chip>
          </div>
        </div>
        <v-alert v-else-if="!trackingState.available" type="info" variant="tonal" density="compact">Loading motion presets…</v-alert>

        <v-divider class="my-2"/>
        <div class="upload-section">
          <v-btn v-if="!showUploadOptions" variant="text" density="compact" color="primary" class="upload-toggle" @click="showUploadOptions = true">Custom motions?</v-btn>
          <template v-else>
            <span class="status-name">Custom motions</span>
            <v-file-input v-model="motionUploadFiles" label="Upload .npz or .json" density="compact" hide-details accept=".npz,.json" prepend-icon="mdi-upload" multiple show-size :disabled="state !== 1" @update:modelValue="onMotionUpload"></v-file-input>
            <v-alert v-if="motionUploadMessage" :type="motionUploadType" variant="tonal" density="compact">{{ motionUploadMessage }}</v-alert>
          </template>
        </div>

        <v-divider class="my-2"/>
        <div class="status-legend">
          <span class="status-name">Render</span><span class="text-caption">{{ renderScaleLabel }}</span>
          <span class="status-name">Sim</span><span class="text-caption">{{ simStepLabel }}</span>
        </div>
        <v-slider v-model="renderScale" min="0.5" max="2.0" step="0.1" density="compact" hide-details @update:modelValue="onRenderScaleChange"></v-slider>
      </v-card-text>
      <v-card-actions><v-btn color="primary" block @click="reset">Reset</v-btn></v-card-actions>
    </v-card>
  </div>
  <v-dialog :model-value="state === 0" persistent max-width="600px">
    <v-card title="Loading"><v-card-text><v-progress-linear indeterminate color="primary"></v-progress-linear>Loading MuJoCo and ONNX policy…</v-card-text></v-card>
  </v-dialog>
  <v-dialog :model-value="state < 0" persistent max-width="600px">
    <v-card title="Error"><v-card-text><span v-if="state === -1">Unexpected error. {{ extra_error_message }}</span><span v-else-if="state === -2">WebAssembly not supported.</span></v-card-text></v-card>
  </v-dialog>
</template>

<script>
import { MuJoCoDemo } from '@/simulation/main.js';
import loadMujoco from 'mujoco-js';
import { parseNpzToClip } from '@/simulation/npzParser.js';

function _ckptLabel(name) { return name.replace(/^G1TRACKING-/, ''); }

export default {
  name: 'DemoPage',
  data: () => ({
    state: 0, extra_error_message: '', keydown_listener: null,
    currentMotion: null, availableMotions: [],
    trackingState: { available: false, currentName: 'default', currentDone: true, refIdx: 0, refLen: 0, transitionLen: 0, motionLen: 0, inTransition: false, isDefault: true },
    trackingTimer: null,
    builtinPolicies: [
      { value: 'g1-tracking-latest', title: 'G1 Tracking (built-in)', policyPath: './examples/checkpoints/g1/tracking_policy_latest.json', source: 'builtin' }
    ],
    bridgePolicies: [],
    currentPolicy: 'g1-tracking-latest',
    isPolicyLoading: false, policyLoadError: '',
    motionUploadFiles: [], motionUploadMessage: '', motionUploadType: 'success', showUploadOptions: false,
    cameraFollowEnabled: true, complianceEnabled: false, complianceThreshold: 10.0, renderScale: 2.0, simStepHz: 0,
    isSmallScreen: false, showSmallScreenAlert: true, isSafari: false, showSafariAlert: true, resize_listener: null,
    bridgeWs: null, bridgeConnected: false,
    fileList: [], localFileList: [], selectedFolderFilter: '', selectedFile: null, selectedFileFolder: 'generated',
    autoReturnDefault: true,
  }),
  watch: {
    'trackingState.currentDone'(done) { if (done && this.autoReturnDefault && this.trackingState?.available && !this.trackingState?.isDefault) this.requestMotion('default'); },
    selectedFolderFilter() { if (this.selectedFile && !this.fileListItems.some(f => f.name === this.selectedFile)) this.selectedFile = null; },
  },
  computed: {
    policies() { return [...this.builtinPolicies, ...this.bridgePolicies]; },
    shouldShowProgress() { const s = this.trackingState; return s && s.available && (s.refLen > 1 || !s.currentDone || !s.isDefault || s.inTransition); },
    progressValue() { const s = this.trackingState; return s && s.refLen > 0 ? Math.max(0, Math.min(100, ((s.refIdx+1)/s.refLen)*100)) : 0; },
    showBackToDefault() { const s = this.trackingState; return s && s.available && !s.isDefault && s.currentDone; },
    showMotionLockedNotice() { const s = this.trackingState; return s && s.available && !s.isDefault && !s.currentDone; },
    showMotionSelect() { const s = this.trackingState; return s && s.available && s.isDefault && s.currentDone && this.motionItems.some(i => !i.disabled); },
    motionItems() {
      return [...this.availableMotions].sort((a,b) => a==='default'?-1:b==='default'?1:a.localeCompare(b)).map(name => ({ title: name.split('_')[0], value: name, disabled: this.isMotionDisabled(name) }));
    },
    motionGroups() {
      const items = this.motionItems.filter(i => i.value !== 'default');
      if (!items.length) return [];
      const lafan=[], amass=[], custom=[];
      for (const item of items) {
        const v = item.value.toLowerCase();
        if (v.includes('[new]')||v.includes('[load]')||v.includes('[bridge]')||v.includes('[t2m]')) custom.push(item);
        else if (v.includes('amass')) amass.push(item);
        else lafan.push(item);
      }
      const g=[]; if (lafan.length) g.push({title:'LAFAN1',items:lafan}); if (amass.length) g.push({title:'AMASS',items:amass}); if (custom.length) g.push({title:'Custom',items:custom}); return g;
    },
    policyItems() { return this.policies.map(p => ({ title: p.title, value: p.value })); },
    policyDescription() { return this.policies.find(p => p.value === this.currentPolicy)?.description ?? ''; },
    effectiveFileList() { return this.bridgeConnected ? this.fileList : this.localFileList; },
    folderFilterOptions() { const f=[...new Set(this.effectiveFileList.map(x=>x.folder))].sort(); return [{value:'',title:'All'},...f.map(x=>({value:x,title:this.folderChipLabel(x)}))]; },
    fileListItems() { let l=this.effectiveFileList; if (this.selectedFolderFilter) l=l.filter(x=>x.folder===this.selectedFolderFilter); return l.map(x=>({...x,title:x.name})); },
    renderScaleLabel() { return `${this.renderScale.toFixed(2)}x`; },
    complianceThresholdLabel() { return this.complianceThreshold.toFixed(1); },
    simStepLabel() { return this.simStepHz&&Number.isFinite(this.simStepHz)?`${this.simStepHz.toFixed(1)} Hz`:'—'; },
  },
  methods: {
    folderChipLabel(f) { return f; },
    folderChipColor(f) { return f==='saved'?'success':f==='dataset'?'info':'primary'; },
    detectSafari() { const u=navigator.userAgent; return /Safari\//.test(u)&&!/Chrome\//.test(u)&&!/Chromium\//.test(u); },
    updateScreenState() { const s=window.innerWidth<500||window.innerHeight<700; if(!s&&this.isSmallScreen)this.showSmallScreenAlert=true; this.isSmallScreen=s; },
    async init() {
      if (typeof WebAssembly!=='object') { this.state=-2; return; }
      try {
        const m=await loadMujoco(); this.demo=new MuJoCoDemo(m); this.demo.setFollowEnabled?.(this.cameraFollowEnabled);
        await this.demo.init(); this.demo.main_loop(); this.demo.params.paused=false;
        this.reapplyCustomMotions(); this.availableMotions=this.getAvailableMotions();
        this.currentMotion=this.demo.params.current_motion??this.availableMotions[0]??null;
        this.complianceEnabled=Boolean(this.demo.params?.compliance_enabled);
        const t=Number(this.demo.params?.compliance_threshold); if(Number.isFinite(t))this.complianceThreshold=t;
        this.startTrackingPoll(); this.renderScale=this.demo.renderScale??this.renderScale;
        const p=this.builtinPolicies.find(x=>x.policyPath===this.demo.currentPolicyPath); if(p)this.currentPolicy=p.value;
        this.state=1;
      } catch(e) { this.state=-1; this.extra_error_message=e.toString(); console.error(e); }
    },
    reapplyCustomMotions() { if(this.demo&&this.customMotions&&Object.keys(this.customMotions).length) this.addMotions(this.customMotions); },
    async onMotionUpload(files) {
      const fl=Array.isArray(files)?files:files instanceof FileList?Array.from(files):files?[files]:[]; if(!fl.length||!this.demo) { this.motionUploadFiles=[]; return; }
      let added=0,failed=0; const prefix='[new] ';
      for(const f of fl) { try { let clip; const ext=(f.name||'').split('.').pop()?.toLowerCase(); if(ext==='npz') clip=await parseNpzToClip(await f.arrayBuffer()); else { const p=JSON.parse(await f.text()); clip=p&&typeof p==='object'&&!Array.isArray(p)?p:null; } if(!clip)continue; const bn=f.name.replace(/\.[^/.]+$/,'').trim()||'motion'; const mn=bn.startsWith(prefix)?bn:`${prefix}${bn}`; const r=this.addMotions({[mn]:clip}); added+=r.added.length; if(r.added.length>0) { if(!this.customMotions)this.customMotions={}; for(const n of r.added)this.customMotions[n]=clip; } } catch{ failed++; } }
      if(added>0)this.availableMotions=this.getAvailableMotions(); this.motionUploadMessage=added>0?`Added ${added} motion(s).`:failed>0?`Failed ${failed} file(s).`:''; this.motionUploadType=failed>0?'warning':'success'; this.motionUploadFiles=[];
    },
    toggleCameraFollow(v) { this.demo?.setFollowEnabled?.(v??this.cameraFollowEnabled); },
    toggleCompliance() { const n=!this.complianceEnabled; if(n){ const c=this.currentMotion??this.demo?.params?.current_motion; if(c&&!this.isMotionComplianceSuitable(c))return; } this.complianceEnabled=n; this.applyComplianceSettings(); },
    onComplianceThresholdChange(v) { this.complianceThreshold=Number(v); this.applyComplianceSettings(); },
    applyComplianceSettings() { if(this.demo?.params) { this.demo.params.compliance_enabled=Boolean(this.complianceEnabled); this.demo.params.compliance_threshold=Number(this.complianceThreshold); } },
    isMotionComplianceSuitable(n) { return this.demo?.policyRunner?.tracking?.isComplianceSuitable?.(n)??true; },
    isMotionDisabled(n) { return n==='default'?true:this.complianceEnabled?!this.isMotionComplianceSuitable(n):false; },
    onMotionChange(v) { if(!this.demo)return; if(!v||v===this.demo.params.current_motion){this.currentMotion=this.demo.params.current_motion??v;return;} if(this.requestMotion(v)){this.currentMotion=v;this.updateTrackingState();}else this.currentMotion=this.demo.params.current_motion; },
    async onPolicyChange(value) {
      if(!this.demo||!value)return; const sel=this.policies.find(p=>p.value===value); if(!sel)return;
      this.isPolicyLoading=true; this.policyLoadError='';
      this.demo.params.paused=true;
      try {
        let cfg, onnxOverride;
        if(sel.source==='bridge'){
          const r=await fetch(`http://127.0.0.1:8766/ckpt/${sel.name}/tracking_policy.json`);
          if(!r.ok)throw new Error(await r.text());
          cfg=await r.json();
          onnxOverride=`http://127.0.0.1:8766/ckpt/${sel.name}/policy.onnx`;
        }
        const path=sel.policyPath||null;
        await this.demo.reloadPolicy(path,{inlineConfig:cfg,onnxPath:onnxOverride});
        this.demo.params.paused=false;
        this.reapplyCustomMotions();
        this.availableMotions=this.getAvailableMotions();
        this.currentMotion=this.demo.params.current_motion??this.availableMotions[0]??null;
        this.updateTrackingState();
      } catch(e){
        this.policyLoadError=e.toString(); console.error(e);
        // Keep paused on failure — broken policy runner shouldn't execute
        if(this.demo.simulation)this.demo.simulation.resetData();
      }
      this.isPolicyLoading=false;
    },
    reset() { if(!this.demo)return; this.demo.resetSimulation(); this.availableMotions=this.getAvailableMotions(); this.currentMotion=this.demo.params.current_motion??this.availableMotions[0]??null; this.updateTrackingState(); },
    backToDefault() { if(!this.demo)return; if(this.requestMotion('default')){this.currentMotion='default';this.updateTrackingState();} },
    startTrackingPoll() { this.stopTrackingPoll(); this.updateTrackingState(); this.updatePerformanceStats(); this.trackingTimer=setInterval(()=>{this.updateTrackingState();this.updatePerformanceStats();},33); },
    stopTrackingPoll() { if(this.trackingTimer){clearInterval(this.trackingTimer);this.trackingTimer=null;} },
    updateTrackingState() { const t=this.demo?.policyRunner?.tracking??null; if(!t){this.trackingState={available:false,currentName:'default',currentDone:true,refIdx:0,refLen:0,transitionLen:0,motionLen:0,inTransition:false,isDefault:true};return;} this.trackingState={...t.playbackState()}; this.availableMotions=t.availableMotions(); const c=this.demo.params.current_motion??this.trackingState.currentName??null; if(c&&this.currentMotion!==c)this.currentMotion=c; },
    updatePerformanceStats() { this.simStepHz=this.demo?.getSimStepHz?.()??this.demo?.simStepHz??0; },
    onRenderScaleChange(v) { this.demo?.setRenderScale?.(v); },
    getAvailableMotions() { return this.demo?.policyRunner?.tracking?.availableMotions()??[]; },
    addMotions(m,o={}) { return this.demo?.policyRunner?.tracking?.addMotions(m,o)??{added:[],skipped:[],invalid:[]}; },
    requestMotion(n) { const t=this.demo?.policyRunner?.tracking??null; if(!t||!this.demo)return false; const a=t.requestMotion(n,this.demo.readPolicyState()); if(a)this.demo.params.current_motion=n; return a; },
    onFileSelect(n) { const f=this.effectiveFileList.find(x=>x.name===n); if(f)this.selectedFileFolder=f.folder; },
    async refreshFileList() { try{this.fileList=await(await fetch('http://127.0.0.1:8766/list')).json();}catch{this.fileList=[];} },
    async refreshLocalFileList() { try{this.localFileList=await(await fetch('/data-index.json')).json();}catch{this.localFileList=[];} },
    refreshLoadFileList() { this.bridgeConnected?this.refreshFileList():this.refreshLocalFileList(); },
    async onLoadFileClick() { if(!this.selectedFile)return; this.bridgeConnected?this.onLoadFile():this.onLoadFileLocal(); },
    async onLoadFile() { if(!this.selectedFile)return; try{await fetch('http://127.0.0.1:8766/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:this.selectedFile,folder:this.selectedFileFolder})});}catch{} },
    async onLoadFileLocal() { if(!this.selectedFile)return; const f=this.selectedFileFolder||this.effectiveFileList.find(x=>x.name===this.selectedFile)?.folder||'dataset'; try{const r=await fetch(`/data/${f}/${this.selectedFile}.npz`); if(!r.ok)throw new Error(r.statusText); const clip=await parseNpzToClip(await r.arrayBuffer()); const mn=`[LOAD] ${this.selectedFile}`; this.addMotions({[mn]:clip},{overwrite:true}); this.availableMotions=this.getAvailableMotions(); if(this.demo&&this.state===1){this.requestMotion(mn);this.currentMotion=mn;} }catch{} },
    triggerLoadNpzInput() { this.$refs.loadNpzInput?.click(); },
    async onLoadNpzFromFile(evt) { const files=evt.target?.files; if(!files?.length)return; let added=0; for(const f of Array.from(files)){try{const clip=await parseNpzToClip(await f.arrayBuffer()); const mn=`[LOAD] ${f.name.replace(/\.[^/.]+$/,'').trim()||'motion'}`; const r=this.addMotions({[mn]:clip}); added+=r.added.length; if(r.added.length>0){this.availableMotions=this.getAvailableMotions(); if(this.demo&&this.state===1){this.requestMotion(mn);this.currentMotion=mn;}}}catch{}} evt.target.value=''; },
    async fetchBridgeCheckpoints() {
      if(!this.bridgeConnected)return;
      try{const r=await fetch('http://127.0.0.1:8766/ckpts'); const list=await r.json(); for(const ck of list){const v=`bridge-${ck.name}`; if(!this.bridgePolicies.find(p=>p.value===v)&&!this.builtinPolicies.find(p=>p.value===v)){this.bridgePolicies.push({value:v,title:`G1 ${_ckptLabel(ck.name)}`,name:ck.name,source:'bridge'});}}}catch{}
    },
    connectBridge() {
      const url='ws://127.0.0.1:8765'; let ws; try{ws=new WebSocket(url);}catch{return;} this.bridgeWs=ws;
      ws.onopen=()=>{this.bridgeConnected=true; this.refreshFileList(); this.fetchBridgeCheckpoints();};
      ws.onmessage=(evt)=>{let msg; try{msg=JSON.parse(evt.data);}catch{return;} if(msg.type!=='motion'||!msg.name||!msg.clip)return; const mn=`[BRIDGE] ${msg.name.replace(/^\[.*?\]\s*/,'')}`; const r=this.addMotions({[mn]:msg.clip},{overwrite:true}); if(r.added.length>0){this.availableMotions=this.getAvailableMotions(); if(this.demo&&this.state===1){this.requestMotion(mn);this.currentMotion=mn;}}};
      ws.onclose=()=>{this.bridgeConnected=false; this.bridgeWs=null; this.refreshLocalFileList(); setTimeout(()=>this.connectBridge(),3000);};
      ws.onerror=()=>ws.close();
    }
  },
  mounted() {
    this.customMotions={}; this.isSafari=this.detectSafari(); this.updateScreenState();
    this.resize_listener=()=>this.updateScreenState(); window.addEventListener('resize',this.resize_listener);
    this.init(); this.connectBridge(); setTimeout(()=>{if(!this.bridgeConnected)this.refreshLocalFileList();},1500);
    this.keydown_listener=e=>{if(e.code==='Backspace')this.reset();}; document.addEventListener('keydown',this.keydown_listener);
  },
  beforeUnmount() {
    this.stopTrackingPoll(); document.removeEventListener('keydown',this.keydown_listener);
    if(this.resize_listener)window.removeEventListener('resize',this.resize_listener);
    if(this.bridgeWs){this.bridgeWs.onclose=null;this.bridgeWs.close();}
  }
};
</script>

<style scoped>
.controls { position:fixed; top:20px; right:20px; width:320px; z-index:1000; }
.global-alerts { position:fixed; top:20px; left:16px; right:16px; max-width:520px; margin:0 auto; display:flex; flex-direction:column; gap:8px; z-index:1200; }
.small-screen-alert,.safari-alert { width:100%; }
.controls-card { max-height:calc(100vh - 40px); }
.controls-body { max-height:calc(100vh - 160px); overflow-y:auto; overscroll-behavior:contain; }
.motion-status { display:flex; flex-direction:column; gap:8px; }
.motion-groups { display:flex; flex-direction:column; gap:8px; margin-top:12px; max-height:200px; overflow-y:auto; }
.motion-group { display:flex; flex-wrap:wrap; align-items:center; gap:6px; }
.motion-chip { text-transform:none; font-size:0.7rem; }
.status-legend { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.status-name { font-weight:600; }
.load-section { display:flex; flex-direction:column; }
.load-section .load-folder-select { width:100%; }
.upload-section { display:flex; flex-direction:column; gap:8px; }
.upload-toggle { padding:0; min-height:unset; font-size:0.85rem; text-transform:none; }
.motion-progress-no-animation,.motion-progress-no-animation *,.motion-progress-no-animation::before,.motion-progress-no-animation::after { transition:none!important; animation:none!important; }
.motion-progress-no-animation :deep(.v-progress-linear__determinate),.motion-progress-no-animation :deep(.v-progress-linear__indeterminate),.motion-progress-no-animation :deep(.v-progress-linear__background) { transition:none!important; animation:none!important; }
</style>
