import {defineConfig} from '@playwright/test';
export default defineConfig({
 testDir:'./tests',timeout:60000,fullyParallel:false,workers:1,
 use:{baseURL:'http://127.0.0.1:18765',trace:'retain-on-failure',launchOptions:process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{}},
 webServer:{command:'../.venv/bin/python -m nowcast.app serve --config ../configs/config.yaml --port 18765',url:'http://127.0.0.1:18765/api/v1/session',reuseExistingServer:false,env:{DATA_DIR:new URL('../data/ui-verification',import.meta.url).pathname}},
 projects:[{name:'desktop',use:{viewport:{width:1440,height:1000}}},{name:'mobile',use:{viewport:{width:390,height:844}}}]
});
