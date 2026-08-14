<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Evaluation</span>
        <h2>评测中心</h2>
        <p>管理合同 Agent 评测数据集、运行评测、对比新旧 Runtime 准确率</p>
      </div>
    </section>

    <!-- Metrics trend -->
    <section class="trend-strip" v-if="trend.length">
      <h3>最近评测趋势</h3>
      <div class="trend-grid">
        <div v-for="r in trend.slice(0, 6)" :key="r.id" class="trend-card">
          <el-tag :type="r.runtimeEngine === 'langgraph' ? 'primary' : 'info'" size="small" effect="plain">
            {{ r.runtimeEngineLabel || formatRuntimeEngine(r.runtimeEngine) }}
          </el-tag>
          <strong>{{ r.datasetName }} v{{ r.datasetVersion }}</strong>
          <div class="trend-metrics">
            <small>目标 {{ r.datasetTypeLabel || formatDatasetType(r.contractType) }}</small>
            <small>召回 {{ formatMetric(r, 'highRiskRecall') }}</small>
            <small>引用 {{ formatMetric(r, 'dualCitationRate') }}</small>
            <small>误报 {{ formatMetric(r, 'falsePositiveRate') }}</small>
          </div>
        </div>
      </div>
    </section>

    <el-tabs v-model="tab">
      <!-- ═══ Datasets Tab ═══ -->
      <el-tab-pane label="数据集" name="datasets">
        <div class="section-actions">
          <el-button type="primary" @click="showCreateDataset = true">+ 新建数据集</el-button>
        </div>

        <el-table :data="datasets" stripe v-if="datasets.length">
          <el-table-column prop="name" label="名称" min-width="150">
            <template #default="{ row }"><strong>{{ row.name }}</strong></template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="80" />
          <el-table-column prop="contractTypeLabel" label="评测目标" width="140">
            <template #default="{ row }">
              {{ row.contractTypeLabel || formatDatasetType(row.contractType) }}
            </template>
          </el-table-column>
          <el-table-column prop="caseCount" label="用例数" width="80" align="center" />
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" effect="plain" size="small">
                {{ row.statusLabel || formatStatus(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button size="small" @click="viewCases(row)">用例</el-button>
              <el-button size="small" @click="startRun(row)">评测</el-button>
              <el-button size="small" type="danger" @click="deleteDataset(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无评测数据集" :image-size="64" />

        <!-- Create dataset dialog -->
        <el-dialog v-model="showCreateDataset" title="新建评测数据集" width="460px">
          <el-form :model="newDataset" label-width="80px">
            <el-form-item label="名称">
              <el-input v-model="newDataset.name" placeholder="数据集名称" />
            </el-form-item>
            <el-form-item label="版本">
              <el-input v-model="newDataset.version" placeholder="如 v1" />
            </el-form-item>
            <el-form-item label="评测目标">
              <el-select v-model="newDataset.contractType" style="width: 100%">
                <el-option label="风险审查" value="CONTRACT_REVIEW" />
                <el-option label="合同要素提取" value="INTAKE" />
                <el-option label="履约日程提取" value="FULFILLMENT_TIMELINE" />
                <el-option label="履约核验" value="FULFILLMENT_CHECK" />
                <el-option label="综合评测" value="COMPREHENSIVE" />
              </el-select>
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="newDataset.description" type="textarea" rows="3" placeholder="描述" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="showCreateDataset = false">取消</el-button>
            <el-button type="primary" @click="createDataset">创建</el-button>
          </template>
        </el-dialog>

        <!-- Add case dialog -->
        <el-dialog v-model="showAddCase" title="添加评测用例" width="680px">
          <el-form :model="newCase" label-width="100px">
            <el-form-item label="用例Key">
              <el-input v-model="newCase.caseKey" placeholder="唯一标识，如 CASE-001" />
            </el-form-item>
            <el-form-item label="标题">
              <el-input v-model="newCase.title" placeholder="用例标题" />
            </el-form-item>
            <div style="color:#909399;line-height:1.6;margin-bottom:8px">
              用例会自动继承评测目标，不再强制选择合同类型。若需要做样本背景区分，后续再补高级标签。
            </div>
            <el-form-item label="合同全文">
              <el-input v-model="newCase.contractText" type="textarea" rows="10" placeholder="粘贴完整合同文本" />
            </el-form-item>
            <el-form-item label="预期发现">
              <el-input v-model="newCase.expectedFindingsJson" type="textarea" rows="5"
                        placeholder='[{"title":"...","severity":"HIGH","clauseType":"PAYMENT"}]' />
              <small style="color:#909399;display:block;margin-top:4px">JSON 数组，每项必须含 title、severity（HIGH/MEDIUM/LOW）、clauseType</small>
            </el-form-item>
            <el-form-item label="不应发现">
              <el-input v-model="newCase.shouldNotFindJson" type="textarea" rows="3"
                        placeholder='["不应被误报的风险点"]' />
              <small style="color:#909399;display:block;margin-top:4px">JSON 数组，列举不应被 Agent 识别为风险的内容</small>
            </el-form-item>
            <el-form-item label="预期引用数">
              <el-input-number v-model="newCase.expectedCitationCount" :min="0" />
            </el-form-item>
            <el-form-item label="合同场景">
              <el-select v-model="newCase.scenario" placeholder="选择合同场景" style="width:100%">
                <el-option label="服务采购" value="SERVICE_PROCUREMENT" />
                <el-option label="工程建设/EPC" value="ENGINEERING_EPC" />
                <el-option label="货物采购" value="GOODS_PROCUREMENT" />
                <el-option label="软件开发/IT" value="SOFTWARE_IT" />
                <el-option label="保密协议" value="NDA" />
                <el-option label="运维/维修/物业" value="OPS_MAINTENANCE" />
                <el-option label="其他混合" value="MIXED" />
              </el-select>
            </el-form-item>
            <el-form-item label="行业">
              <el-input v-model="newCase.industry" placeholder="如：制造业、金融、医疗、互联网..." />
            </el-form-item>
            <el-form-item label="难度">
              <el-select v-model="newCase.difficulty" placeholder="选择难度" style="width:100%">
                <el-option label="明确条款（Easy）" value="EASY" />
                <el-option label="模糊条款（Fuzzy）" value="FUZZY" />
                <el-option label="缺失条款（Missing）" value="MISSING_CLAUSE" />
                <el-option label="冲突条款（Conflicting）" value="CONFLICTING" />
                <el-option label="OCR/扫描噪声" value="OCR_NOISE" />
                <el-option label="金额/日期歧义" value="AMBIGUITY" />
                <el-option label="跨段落分散" value="CROSS_PARAGRAPH" />
                <el-option label="仅附件出现" value="ATTACHMENT_ONLY" />
              </el-select>
            </el-form-item>
            <el-form-item label="噪声级别">
              <el-select v-model="newCase.noiseLevel" placeholder="噪声级别" style="width:100%">
                <el-option label="无" value="NONE" />
                <el-option label="低" value="LOW" />
                <el-option label="中" value="MEDIUM" />
                <el-option label="高" value="HIGH" />
              </el-select>
            </el-form-item>
            <el-form-item label="引用要求">
              <el-checkbox v-model="newCase.mustHaveContractCitation" :true-value="1" :false-value="0">必须引用合同条款</el-checkbox>
              <el-checkbox v-model="newCase.mustHavePolicyCitation" :true-value="1" :false-value="0" style="margin-left:16px">必须引用政策法规</el-checkbox>
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="showAddCase = false">取消</el-button>
            <el-button type="primary" @click="addCase">添加</el-button>
          </template>
        </el-dialog>

        <!-- Case detail dialog -->
        <el-dialog v-model="showCaseDetail" title="用例详情" width="720px">
          <template v-if="viewingCase">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="Key" :span="1">{{ viewingCase.caseKey }}</el-descriptions-item>
              <el-descriptions-item label="ID" :span="1">{{ viewingCase.id }}</el-descriptions-item>
              <el-descriptions-item label="标题" :span="2">{{ viewingCase.title }}</el-descriptions-item>
              <el-descriptions-item label="合同类型" :span="1">{{ viewingCase.contractTypeLabel || viewingCase.contractType }}</el-descriptions-item>
              <el-descriptions-item label="合同场景" :span="1">{{ scenarioLabel(viewingCase.scenario) }}</el-descriptions-item>
              <el-descriptions-item label="行业" :span="1">{{ viewingCase.industry || '（未设置）' }}</el-descriptions-item>
              <el-descriptions-item label="难度" :span="1">
                <el-tag size="small" :type="difficultyTagType(viewingCase.difficulty)">{{ difficultyLabel(viewingCase.difficulty) }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="噪声级别" :span="1">{{ noiseLabel(viewingCase.noiseLevel) }}</el-descriptions-item>
              <el-descriptions-item label="预期引用数" :span="1">{{ viewingCase.expectedCitationCount ?? 0 }}</el-descriptions-item>
              <el-descriptions-item label="必须引用合同" :span="1">{{ viewingCase.mustHaveContractCitation ? '是' : '否' }}</el-descriptions-item>
              <el-descriptions-item label="必须引用政策" :span="1">{{ viewingCase.mustHavePolicyCitation ? '是' : '否' }}</el-descriptions-item>
            </el-descriptions>
            <h4 style="margin:16px 0 8px;color:#303133">合同全文</h4>
            <div class="contract-text-viewer" v-html="renderedContractText()"></div>
            <h4 style="margin:16px 0 8px;color:#303133">预期发现 (expectedFindingsJson)</h4>
            <pre class="json-block">{{ formatJson(viewingCase.expectedFindingsJson) }}</pre>
            <h4 style="margin:16px 0 8px;color:#303133">不应发现 (shouldNotFindJson)</h4>
            <pre class="json-block">{{ formatJson(viewingCase.shouldNotFindJson) }}</pre>
          </template>
          <template #footer>
            <el-button @click="showCaseDetail = false">关闭</el-button>
          </template>
        </el-dialog>

        <!-- Start run dialog -->
        <el-dialog v-model="showStartRun" title="发起评测" width="520px">
          <el-form label-width="90px">
            <el-form-item label="数据集">
              <strong>{{ startRunDs?.name }} v{{ startRunDs?.version }}</strong>
            </el-form-item>
            <el-form-item label="Runtime">
              <el-select v-model="startRunRuntime" style="width: 100%">
                <el-option label="Legacy (六阶段流水线)" value="legacy" :disabled="legacyBlocked" />
                <el-option label="LangGraph (状态图)" value="langgraph" />
                <el-option label="LangGraph v2 (风险审查试点)" value="langgraph_v2" :disabled="v2Blocked" />
              </el-select>
              <small v-if="legacyBlocked" style="color:#e6a23c;display:block;margin-top:4px">
                Legacy 引擎不支持该数据集的任务类型，仅可选用 LangGraph
              </small>
              <small v-if="v2Blocked" style="color:#909399;display:block;margin-top:4px">
                v2 图仅实现风险审查任务，该数据集请选用 Legacy / LangGraph
              </small>
            </el-form-item>
            <el-divider content-position="left" style="margin:12px 0">模型与提示词</el-divider>
            <el-form-item label="模型">
              <el-select v-model="startRunFeatures.model" style="width: 100%" clearable placeholder="使用全局默认">
                <el-option label="DeepSeek V3" value="deepseek-chat" />
                <el-option label="DeepSeek R1" value="deepseek-reasoner" />
                <el-option label="Claude Sonnet 5" value="claude-sonnet-5" />
                <el-option label="Claude Opus 5" value="claude-opus-5" />
                <el-option label="Qwen Max" value="qwen-max" />
              </el-select>
            </el-form-item>
            <el-form-item label="提示词版本">
              <el-select v-model="startRunFeatures.promptVersion" style="width: 100%" clearable placeholder="使用默认版本">
                <el-option label="contract-review-graph-v1 (当前)" value="contract-review-graph-v1" />
                <el-option label="contract-review-graph-v2" value="contract-review-graph-v2" />
              </el-select>
            </el-form-item>
            <el-divider content-position="left" style="margin:12px 0">功能组件</el-divider>
            <el-form-item label="Rerank">
              <el-switch v-model="startRunFeatures.rerank" active-text="LLM 重排序" inactive-text="关键词加分" />
            </el-form-item>
            <el-divider content-position="left" style="margin:12px 0">
              检索参数
              <el-button size="small" text @click="showRetrievalOpts = !showRetrievalOpts" style="margin-left:8px">
                {{ showRetrievalOpts ? '收起' : '展开' }}
              </el-button>
            </el-divider>
            <template v-if="showRetrievalOpts">
              <el-form-item label="召回乘数">
                <el-input-number v-model="startRunFeatures.recallMultiplier" :min="2" :max="15" size="small" />
                <small style="color:#909399;margin-left:8px">top_k × 乘数 = 粗排候选数，默认 6</small>
              </el-form-item>
              <el-form-item label="召回下限">
                <el-input-number v-model="startRunFeatures.recallMin" :min="10" :max="100" size="small" />
                <small style="color:#909399;margin-left:8px">最少召回候选数，默认 30</small>
              </el-form-item>
              <el-form-item label="召回上限">
                <el-input-number v-model="startRunFeatures.recallMax" :min="20" :max="200" size="small" />
                <small style="color:#909399;margin-left:8px">最多召回候选数，默认 50</small>
              </el-form-item>
            </template>
            <el-divider content-position="left" style="margin:12px 0">P1 反思与控制</el-divider>
            <el-form-item label="定向检索重试">
              <el-select v-model="startRunFeatures.targetedRetrievalRetries" style="width: 120px" :disabled="startRunRuntime === 'legacy'">
                <el-option label="0 (跳过)" :value="0" />
                <el-option label="1 (默认)" :value="1" />
                <el-option label="2" :value="2" />
              </el-select>
              <small style="color:#909399;margin-left:8px">{{ startRunRuntime === 'legacy' ? '仅 LangGraph 生效' : '覆盖缺口后二次检索次数' }}</small>
            </el-form-item>
            <el-form-item label="覆盖反思">
              <el-switch v-model="startRunFeatures.coverageReflection" active-text="启用" inactive-text="跳过" :disabled="startRunRuntime === 'legacy'" />
              <small style="color:#909399;margin-left:8px">{{ startRunRuntime === 'legacy' ? '仅 LangGraph 生效' : '关闭后直接 CONFIRMED，跳过反思阶段' }}</small>
            </el-form-item>
            <el-divider content-position="left" style="margin:12px 0">P2 生成参数</el-divider>
            <el-form-item label="温度">
              <el-input-number v-model="startRunFeatures.temperature" :min="0" :max="2" :step="0.1" :precision="1" size="small" />
              <small style="color:#909399;margin-left:8px">LLM 采样温度，0 = 使用提示词默认值</small>
            </el-form-item>
            <el-form-item label="用例超时(秒)">
              <el-input-number v-model="startRunFeatures.caseTimeoutSeconds" :min="300" :max="7200" :step="300" size="small" />
              <small style="color:#909399;margin-left:8px">单例超时上限，v2 建议 ≥ 2400</small>
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="showStartRun = false">取消</el-button>
            <el-button type="primary" :loading="startingRun" @click="doStartRun">开始评测</el-button>
          </template>
        </el-dialog>

        <!-- Cases sub-panel -->
        <div v-if="selectedDataset" class="cases-panel">
          <div class="cases-head">
            <h3>{{ selectedDataset.name }} · 用例列表</h3>
            <el-button type="primary" size="small" @click="showAddCase = true">+ 添加用例</el-button>
          </div>
          <el-table :data="cases" stripe v-if="cases.length">
            <el-table-column prop="caseKey" label="Key" width="100" />
            <el-table-column prop="title" label="标题" min-width="160" />
            <el-table-column label="场景" width="100" align="center">
              <template #default="{ row }">
                <el-tag size="small" effect="plain" type="">{{ scenarioLabel(row.scenario) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="难度" width="100" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="difficultyTagType(row.difficulty)">{{ difficultyLabel(row.difficulty) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="expectedFindingCount" label="预期发现" width="80" align="center" />
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" @click="viewCaseDetail(row.id)">详情</el-button>
                <el-button size="small" type="danger" @click="deleteCase(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无用例" :image-size="48" />
          <el-button class="back-btn" @click="selectedDataset = null; cases = []">← 返回数据集列表</el-button>
        </div>
      </el-tab-pane>

      <!-- ═══ Runs Tab ═══ -->
      <el-tab-pane label="评测记录" name="runs">
        <el-table :data="runs" stripe v-if="runs.length">
          <el-table-column label="数据集" min-width="180">
            <template #default="{ row }">
              <div style="display:flex;flex-direction:column;gap:4px">
                <strong>{{ row.datasetName }} v{{ row.datasetVersion }}</strong>
                <small style="color:#909399">{{ row.datasetTypeLabel || formatDatasetType(row.contractType) }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="Runtime" width="150" align="center">
            <template #default="{ row }">
              <div style="display:flex;flex-direction:column;gap:2px;align-items:center">
                <el-tag :type="row.runtimeEngine === 'langgraph' ? 'primary' : 'info'" effect="plain" size="small">
                  {{ row.runtimeEngineLabel || formatRuntimeEngine(row.runtimeEngine) }}
                </el-tag>
                <el-tooltip v-if="row.runtimeEngineMismatch" content="请求的引擎与实际执行的引擎不一致（如旧版 API 服务不认识 v2 时回退 Legacy）">
                  <el-tag type="danger" effect="plain" size="small">实际: {{ row.actualRuntimeEngineLabel || row.actualRuntimeEngine }}</el-tag>
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="功能组件" width="200" align="center">
            <template #default="{ row }">
              <div style="display:flex;flex-wrap:wrap;gap:3px;justify-content:center">
                <el-tag v-if="parseFeatures(row.featuresJson).model" type="warning" effect="plain" size="small">{{ parseFeatures(row.featuresJson).model }}</el-tag>
                <el-tag v-if="parseFeatures(row.featuresJson).promptVersion" type="" effect="plain" size="small">{{ parseFeatures(row.featuresJson).promptVersion }}</el-tag>
                <el-tag v-if="parseFeatures(row.featuresJson).rerank !== false" type="info" effect="plain" size="small">请求重排序</el-tag>
                <el-tag v-else type="info" effect="plain" size="small">无重排序</el-tag>
                <el-tag
                  v-if="rerankExecution(row).label"
                  :type="rerankExecution(row).type"
                  effect="plain"
                  size="small"
                >{{ rerankExecution(row).label }}</el-tag>
                <el-tag v-if="row.runtimeEngine === 'langgraph' && parseFeatures(row.featuresJson).targetedRetrievalRetries > 0" type="primary" effect="plain" size="small">定向检索×{{ parseFeatures(row.featuresJson).targetedRetrievalRetries }}</el-tag>
                <el-tag v-if="row.runtimeEngine === 'langgraph' && parseFeatures(row.featuresJson).coverageReflection === false" type="danger" effect="plain" size="small">无覆盖反思</el-tag>
                <el-tag v-if="parseFeatures(row.featuresJson).temperature > 0" type="warning" effect="plain" size="small">T={{ parseFeatures(row.featuresJson).temperature }}</el-tag>
                <el-tag v-if="!parseFeatures(row.featuresJson).model && !parseFeatures(row.featuresJson).promptVersion && parseFeatures(row.featuresJson).rerank !== false && !(row.runtimeEngine === 'langgraph' && parseFeatures(row.featuresJson).targetedRetrievalRetries > 0) && !(row.runtimeEngine === 'langgraph' && parseFeatures(row.featuresJson).coverageReflection === false) && !(parseFeatures(row.featuresJson).temperature > 0)" type="info" effect="plain" size="small">默认配置</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="statusLabel" label="状态" width="90" align="center">
            <template #default="{ row }">{{ row.statusLabel || formatStatus(row.status) }}</template>
          </el-table-column>
          <el-table-column label="进度" width="180" align="center">
            <template #default="{ row }">
              <div class="run-progress">
                <el-progress :percentage="evalPercent(row)" :stroke-width="8" :show-text="false" />
                <small>{{ progressText(row) }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="执行成功" width="90" align="center">
            <template #default="{ row }">{{ formatExecutedCases(row) }}</template>
          </el-table-column>
          <el-table-column label="完整报告" width="90" align="center">
            <template #default="{ row }">{{ formatEffectiveCases(row) }}</template>
          </el-table-column>
          <el-table-column label="风险召回" width="100" align="center">
            <template #default="{ row }">{{ formatMetric(row, 'highRiskRecall') }}</template>
          </el-table-column>
          <el-table-column label="引用率" width="90" align="center">
            <template #default="{ row }">{{ formatMetric(row, 'dualCitationRate') }}</template>
          </el-table-column>
          <el-table-column label="误报率" width="90" align="center">
            <template #default="{ row }">{{ formatMetric(row, 'falsePositiveRate') }}</template>
          </el-table-column>
          <el-table-column label="时间" width="140">
            <template #default="{ row }">{{ formatDate(row.startedAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" align="center">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="viewRunDetail(row.id)">详情</el-button>
              <el-button size="small" type="danger" @click="deleteRun(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无评测记录" :image-size="64" />
      </el-tab-pane>

      <!-- ═══ Run detail dialog ═══ -->
      <el-dialog v-model="showRunDetail" title="评测运行详情" width="92%" top="3vh" destroy-on-close>
        <template v-if="viewingRun && !viewingResult">
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="Run ID">{{ viewingRun.id }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag size="small" :type="statusTagType(viewingRun.status)">{{ viewingRun.statusLabel || formatStatus(viewingRun.status) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="Runtime">{{ viewingRun.runtimeEngineLabel || formatRuntimeEngine(viewingRun.runtimeEngine) }}</el-descriptions-item>
            <el-descriptions-item v-if="viewingRun.runtimeEngineMismatch" label="实际执行引擎">
              <el-tag type="danger" size="small">{{ viewingRun.actualRuntimeEngineLabel || viewingRun.actualRuntimeEngine }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="数据集">{{ viewingRun.datasetName }} v{{ viewingRun.datasetVersion }}</el-descriptions-item>
            <el-descriptions-item label="评测目标">{{ viewingRun.datasetTypeLabel || formatDatasetType(viewingRun.contractType) }}</el-descriptions-item>
            <el-descriptions-item label="图 / 版本">{{ viewingRun.graphName || '-' }} / {{ viewingRun.graphVersion || '-' }}</el-descriptions-item>
            <el-descriptions-item label="LLM 模型">{{ viewingRun.llmModel || '（默认）' }}</el-descriptions-item>
            <el-descriptions-item label="提示词版本">{{ viewingRun.promptVersion || '（默认）' }}</el-descriptions-item>
            <el-descriptions-item label="风险召回">{{ formatMetric(viewingRun, 'highRiskRecall') }}</el-descriptions-item>
            <el-descriptions-item label="双引用率">{{ formatMetric(viewingRun, 'dualCitationRate') }}</el-descriptions-item>
            <el-descriptions-item label="误报率">{{ formatMetric(viewingRun, 'falsePositiveRate') }}</el-descriptions-item>
            <el-descriptions-item label="Schema 有效率">{{ formatMetric(viewingRun, 'schemaValidRate') }}</el-descriptions-item>
            <el-descriptions-item label="用例数">{{ viewingRun.caseCount }}</el-descriptions-item>
            <el-descriptions-item label="成功执行">{{ viewingRun.passedCount }}</el-descriptions-item>
            <el-descriptions-item label="当前步">{{ viewingRun.currentStep || '-' }}</el-descriptions-item>
            <el-descriptions-item label="排队位置">{{ viewingRun.queuePosition ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="环境状态">{{ viewingRun.environmentStatus || '-' }}</el-descriptions-item>
            <el-descriptions-item label="开始时间" :span="2">{{ formatDate(viewingRun.startedAt) }}</el-descriptions-item>
            <el-descriptions-item label="结束时间" :span="2">{{ formatDate(viewingRun.finishedAt) }}</el-descriptions-item>
            <el-descriptions-item label="创建时间" :span="2">{{ formatDate(viewingRun.createTime) }}</el-descriptions-item>
          </el-descriptions>

          <el-collapse style="margin-top:12px">
            <el-collapse-item title="功能特性 (featuresJson)" name="features">
              <pre class="json-block">{{ formatJson(viewingRun.featuresJson) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="汇总指标 (summaryJson)" name="summary">
              <pre class="json-block">{{ formatJson(viewingRun.summaryJson) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="环境快照 (environmentSnapshotJson)" name="env">
              <pre class="json-block">{{ formatJson(viewingRun.environmentSnapshotJson) }}</pre>
            </el-collapse-item>
          </el-collapse>

          <h4 style="margin:16px 0 8px;color:#303133">逐用例结果 ({{ (viewingRun.results || []).length }})</h4>
          <el-table :data="viewingRun.results" stripe size="small" v-if="viewingRun.results?.length">
            <el-table-column prop="caseId" label="Case" width="60" align="center" />
            <el-table-column prop="caseKey" label="Key" width="110" show-overflow-tooltip />
            <el-table-column prop="caseTitle" label="标题" min-width="160" show-overflow-tooltip />
            <el-table-column label="模式" width="95" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="analysisModeTagType(row.analysisMode)">{{ row.analysisModeLabel || formatAnalysisMode(row.analysisMode) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="召回" width="75" align="center">
              <template #default="{ row }">{{ formatMetric(row, 'highRecall') }}</template>
            </el-table-column>
            <el-table-column label="双引用" width="75" align="center">
              <template #default="{ row }">{{ formatMetric(row, 'dualCitationRate') }}</template>
            </el-table-column>
            <el-table-column label="误报" width="60" align="center">
              <template #default="{ row }">{{ row.falsePositives ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="风险分" width="70" align="center">
              <template #default="{ row }">{{ row.riskScore ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="发现数" width="70" align="center">
              <template #default="{ row }">{{ row.findingCount }}</template>
            </el-table-column>
            <el-table-column label="Schema" width="70" align="center">
              <template #default="{ row }">{{ formatMetric(row, 'schemaValidRate') }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" text @click="showResultDetail(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无用例结果" :image-size="48" />
        </template>

        <template v-else-if="viewingResult">
          <el-button size="small" text @click="backToRunDetail()">← 返回运行详情</el-button>
          <el-descriptions :column="3" border size="small" style="margin-top:8px">
            <el-descriptions-item label="Case ID">{{ viewingResult.caseId }}</el-descriptions-item>
            <el-descriptions-item label="Case Key">{{ viewingResult.caseKey }}</el-descriptions-item>
            <el-descriptions-item label="标题" :span="2">{{ viewingResult.caseTitle }}</el-descriptions-item>
            <el-descriptions-item label="场景">{{ scenarioLabel(viewingResult.scenario) }}</el-descriptions-item>
            <el-descriptions-item label="难度">{{ difficultyLabel(viewingResult.difficulty) }}</el-descriptions-item>
            <el-descriptions-item label="噪声">{{ noiseLabel(viewingResult.noiseLevel) }}</el-descriptions-item>
            <el-descriptions-item label="分析模式">
              <el-tag size="small" :type="analysisModeTagType(viewingResult.analysisMode)">{{ viewingResult.analysisModeLabel || formatAnalysisMode(viewingResult.analysisMode) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="召回">{{ formatMetric(viewingResult, 'highRecall') }}</el-descriptions-item>
            <el-descriptions-item label="双引用">{{ formatMetric(viewingResult, 'dualCitationRate') }}</el-descriptions-item>
            <el-descriptions-item label="误报">{{ viewingResult.falsePositives ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="风险分">{{ viewingResult.riskScore ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="发现数">{{ viewingResult.findingCount }}</el-descriptions-item>
            <el-descriptions-item label="Schema 有效">{{ formatMetric(viewingResult, 'schemaValidRate') }}</el-descriptions-item>
            <el-descriptions-item label="成功">{{ viewingResult.success ? '是' : '否' }}</el-descriptions-item>
            <el-descriptions-item label="证据快照" :span="2">
              <span v-if="caseEvidence.evidenceSnapshotHash" class="mono-tiny">{{ caseEvidence.evidenceSnapshotHash.slice(0, 24) }}…</span>
              <span v-else>-</span>
            </el-descriptions-item>
            <el-descriptions-item label="文档版本">{{ caseEvidence.documentVersion || '-' }}</el-descriptions-item>
            <el-descriptions-item v-if="viewingResult.errorMessage" label="错误信息" :span="3">
              <span style="color:#c0392b">{{ viewingResult.errorMessage }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <h4 style="margin:16px 0 8px;color:#303133">预期发现 (expectedFindingsJson)</h4>
          <pre class="json-block">{{ formatJson(viewingResult.expectedFindingsJson) }}</pre>
          <h4 style="margin:12px 0 8px;color:#303133">不应发现 (shouldNotFindJson)</h4>
          <pre class="json-block">{{ formatJson(viewingResult.shouldNotFindJson) }}</pre>

          <h4 style="margin:12px 0 8px;color:#303133">实际发现 ({{ actualFindings.length }})</h4>
          <el-table :data="actualFindings" stripe size="small" v-if="actualFindings.length">
            <el-table-column prop="severity" label="级别" width="80" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="severityTagType(row.severity)">{{ row.severity }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
            <el-table-column prop="riskDimension" label="维度" width="120" show-overflow-tooltip />
            <el-table-column label="证据" width="140" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.contractCitation || (row.contractCitationIds || []).length" size="small" effect="plain" type="success">合同引用</el-tag>
                <el-tag v-if="row.policyCitation || (row.policyCitationIds || []).length" size="small" effect="plain" type="warning">制度引用</el-tag>
                <span v-if="!row.contractCitation && !(row.contractCitationIds || []).length && !row.policyCitation && !(row.policyCitationIds || []).length">-</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="无发现" :image-size="48" />

          <el-collapse style="margin-top:12px">
            <el-collapse-item title="完整产物 (resultJson)" name="artifact">
              <pre class="json-block artifact-block">{{ formatJson(viewingResult.resultJson) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </template>
        <template #footer>
          <el-button @click="closeRunDetail()">关闭</el-button>
        </template>
      </el-dialog>

      <!-- ═══ Compare Tab ═══ -->
      <el-tab-pane label="版本对比" name="compare">
        <div class="compare-controls">
          <el-select v-model="compareId1" placeholder="选择 Run 1" style="width: 200px">
            <el-option v-for="r in runs" :key="r.id" :label="`${r.datasetName} · ${(r.runtimeEngineLabel || formatRuntimeEngine(r.runtimeEngine))} · #${r.id}`" :value="r.id" />
          </el-select>
          <span class="vs">vs</span>
          <el-select v-model="compareId2" placeholder="选择 Run 2" style="width: 200px">
            <el-option v-for="r in runs" :key="r.id" :label="`${r.datasetName} · ${(r.runtimeEngineLabel || formatRuntimeEngine(r.runtimeEngine))} · #${r.id}`" :value="r.id" />
          </el-select>
          <el-button type="primary" @click="doCompare">对比</el-button>
        </div>

        <table v-if="compareDiffs.length" class="compare-table">
          <thead>
            <tr>
              <th>用例</th>
              <th>召回1</th>
              <th>召回2</th>
              <th>引用1</th>
              <th>引用2</th>
              <th>模式1</th>
              <th>模式2</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in compareDiffs" :key="d.caseId" :class="{ 'has-diff': d.recall1 !== d.recall2 || d.mode1 !== d.mode2 }">
              <td>{{ d.caseTitle }}</td>
              <td>{{ (d.recall1 * 100).toFixed(0) }}%</td>
              <td>{{ (d.recall2 * 100).toFixed(0) }}%</td>
              <td>{{ (d.dualCite1 * 100).toFixed(0) }}%</td>
              <td>{{ (d.dualCite2 * 100).toFixed(0) }}%</td>
              <td>{{ d.mode1Label || formatAnalysisMode(d.mode1) }}</td>
              <td>{{ d.mode2Label || formatAnalysisMode(d.mode2) }}</td>
            </tr>
          </tbody>
        </table>
        <el-empty v-else description="选择两个 Run 进行对比" :image-size="64" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index.js'

const tab = ref('datasets')
const datasets = ref([])
const runs = ref([])
const trend = ref([])
const cases = ref([])
const selectedDataset = ref(null)
const showCreateDataset = ref(false)
const showAddCase = ref(false)
const showCaseDetail = ref(false)
const viewingCase = ref(null)
const compareId1 = ref(null)
const compareId2 = ref(null)
const compareDiffs = ref([])

const newDataset = ref({ name: '', version: 'v1', contractType: 'CONTRACT_REVIEW', description: '' })
const newCase = ref({ caseKey: '', title: '', contractText: '', expectedFindingsJson: '[]', shouldNotFindJson: '[]', expectedCitationCount: 0, scenario: '', industry: '', difficulty: '', noiseLevel: '', mustHaveContractCitation: 0, mustHavePolicyCitation: 0 })
const showStartRun = ref(false)
const startRunDs = ref(null)
const startRunRuntime = ref('legacy')
// Legacy 引擎无提取/日程任务的实现，这些数据集只能跑 LangGraph
const legacyBlocked = computed(() => {
  const t = (startRunDs.value?.contractType || '').toUpperCase()
  return ['INTAKE', 'ELEMENT_EXTRACTION', 'FULFILLMENT_TIMELINE', 'TIMELINE_EXTRACTION'].includes(t)
})
// v2 试点图只实现了风险审查任务，其余类型仍只有 v1 图可跑
const v2Blocked = computed(() => {
  const t = (startRunDs.value?.contractType || '').toUpperCase()
  return !['CONTRACT_REVIEW', 'RISK_REVIEW'].includes(t)
})
const startRunFeatures = ref({ rerank: true, model: '', promptVersion: '', recallMultiplier: 0, recallMin: 0, recallMax: 0, targetedRetrievalRetries: 1, coverageReflection: true, temperature: 0, caseTimeoutSeconds: 2400 })
const showRetrievalOpts = ref(false)
const startingRun = ref(false)
const showRunDetail = ref(false)
const viewingRun = ref(null)
const viewingResult = ref(null)

onMounted(() => { loadAll() })

async function loadAll() {
  try { datasets.value = (await api.get('/api/admin/eval/datasets')).data.data || [] } catch {}
  try { runs.value = (await api.get('/api/admin/eval/runs')).data.data || [] } catch {}
  try { trend.value = (await api.get('/api/admin/eval/metrics/trend')).data.data || [] } catch {}
}

async function createDataset() {
  try {
    await api.post('/api/admin/eval/datasets', newDataset.value)
    ElMessage.success('数据集已创建')
    showCreateDataset.value = false
    newDataset.value = { name: '', version: 'v1', contractType: 'CONTRACT_REVIEW', description: '' }
    loadAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '创建失败')
  }
}

async function deleteDataset(id) {
  try {
    await ElMessageBox.confirm('删除数据集将同时删除所有用例，确定？', '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await api.delete(`/api/admin/eval/datasets/${id}`)
    ElMessage.success('数据集已删除')
    loadAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '删除失败')
  }
}

async function deleteRun(id) {
  try {
    await ElMessageBox.confirm('确定删除此评测记录？将同时删除关联的结果数据。', '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await api.delete(`/api/admin/eval/runs/${id}`)
    ElMessage.success('评测记录已删除')
    loadAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '删除失败')
  }
}

async function addCase() {
  if (!newCase.value.caseKey || !newCase.value.title || !newCase.value.contractText) {
    ElMessage.warning('用例Key、标题和合同全文为必填')
    return
  }
  try {
    await api.post(`/api/admin/eval/datasets/${selectedDataset.value.id}/cases`, {
      caseKey: newCase.value.caseKey,
      title: newCase.value.title,
      contractType: selectedDataset.value.contractType || '',
      contractText: newCase.value.contractText,
      expectedFindingsJson: newCase.value.expectedFindingsJson,
      shouldNotFindJson: newCase.value.shouldNotFindJson,
      expectedCitationCount: newCase.value.expectedCitationCount,
      scenario: newCase.value.scenario,
      industry: newCase.value.industry,
      difficulty: newCase.value.difficulty,
      noiseLevel: newCase.value.noiseLevel,
      mustHaveContractCitation: newCase.value.mustHaveContractCitation,
      mustHavePolicyCitation: newCase.value.mustHavePolicyCitation,
    })
    ElMessage.success('用例已添加')
    showAddCase.value = false
    newCase.value = { caseKey: '', title: '', contractText: '', expectedFindingsJson: '[]', shouldNotFindJson: '[]', expectedCitationCount: 0, scenario: '', industry: '', difficulty: '', noiseLevel: '', mustHaveContractCitation: 0, mustHavePolicyCitation: 0 }
    viewCases(selectedDataset.value)
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '添加失败')
  }
}

async function viewCases(ds) {
  selectedDataset.value = ds
  try { cases.value = (await api.get(`/api/admin/eval/datasets/${ds.id}/cases`)).data.data || [] } catch {}
}

async function startRun(ds) {
  startRunDs.value = ds
  startRunRuntime.value = legacyBlocked.value ? 'langgraph' : 'legacy'
  startRunFeatures.value = { rerank: true, model: '', promptVersion: '', recallMultiplier: 0, recallMin: 0, recallMax: 0, targetedRetrievalRetries: 1, coverageReflection: true, temperature: 0, caseTimeoutSeconds: 2400 }
  showRetrievalOpts.value = false
  showStartRun.value = true
}

async function doStartRun() {
  if (startingRun.value) return
  if (startRunRuntime.value === 'legacy' && legacyBlocked.value) {
    ElMessage.error('Legacy 引擎不支持该数据集的任务类型，请改用 LangGraph')
    return
  }
  startingRun.value = true
  try {
    await api.post('/api/admin/eval/runs', {
      datasetId: startRunDs.value.id,
      runtime: startRunRuntime.value,
      features: JSON.stringify(startRunFeatures.value),
    })
    ElMessage.success('评测已发起')
    showStartRun.value = false
    loadAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '发起失败')
  } finally {
    startingRun.value = false
  }
}

async function viewCaseDetail(caseId) {
  try {
    viewingCase.value = (await api.get(`/api/admin/eval/cases/${caseId}`)).data.data || null
    showCaseDetail.value = true
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '获取用例详情失败')
  }
}

function scenarioLabel(v) {
  return {
    SERVICE_PROCUREMENT: '服务采购', ENGINEERING_EPC: '工程/EPC',
    GOODS_PROCUREMENT: '货物采购', SOFTWARE_IT: '软件/IT',
    NDA: '保密协议', OPS_MAINTENANCE: '运维/物业', MIXED: '混合',
  }[v] || v || '-'
}

function difficultyLabel(v) {
  return {
    EASY: '明确', FUZZY: '模糊', MISSING_CLAUSE: '缺失',
    CONFLICTING: '冲突', OCR_NOISE: 'OCR噪声', AMBIGUITY: '歧义',
    CROSS_PARAGRAPH: '跨段落', ATTACHMENT_ONLY: '仅附件',
  }[v] || v || '-'
}

function noiseLabel(v) {
  return { NONE:'无', LOW:'低', MEDIUM:'中', HIGH:'高' }[v] || v || '无'
}

function difficultyTagType(v) {
  return {
    EASY: 'success', FUZZY: 'warning', MISSING_CLAUSE: 'danger',
    CONFLICTING: 'danger', OCR_NOISE: 'info', AMBIGUITY: 'warning',
    CROSS_PARAGRAPH: '', ATTACHMENT_ONLY: 'info',
  }[v] || ''
}

function formatJson(v) {
  if (!v) return '（空）'
  let obj
  try { obj = JSON.parse(v) } catch { return v }
  return JSON.stringify(obj, null, 2)
}

function renderedContractText() {
  if (!viewingCase.value?.contractText) return '<span style="color:#909399">（无合同文本）</span>'
  return viewingCase.value.contractText
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}

async function deleteCase(id) {
  try {
    await ElMessageBox.confirm('确定删除此用例？', '确认', { type: 'warning' })
  } catch { return }
  try {
    await api.delete(`/api/admin/eval/cases/${id}`)
    ElMessage.success('用例已删除')
    viewCases(selectedDataset.value)
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '删除失败')
  }
}

async function doCompare() {
  if (!compareId1.value || !compareId2.value) return
  try {
    const r = await api.get(`/api/admin/eval/runs/compare?runId1=${compareId1.value}&runId2=${compareId2.value}`)
    compareDiffs.value = r.data.data?.diffs || []
  } catch {
    ElMessage.error('对比请求失败')
  }
}

async function viewRunDetail(runId) {
  try {
    const r = await api.get(`/api/admin/eval/runs/${runId}`)
    viewingRun.value = r.data.data || null
    viewingResult.value = null
    showRunDetail.value = true
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '获取评测详情失败')
  }
}

function showResultDetail(row) {
  viewingResult.value = row
}

function backToRunDetail() {
  viewingResult.value = null
}

function closeRunDetail() {
  showRunDetail.value = false
  viewingRun.value = null
  viewingResult.value = null
}

const actualFindings = computed(() => {
  if (!viewingResult.value?.resultJson) return []
  let artifact
  try { artifact = JSON.parse(viewingResult.value.resultJson) } catch { return [] }
  return Array.isArray(artifact?.findings) ? artifact.findings : []
})

const caseEvidence = computed(() => {
  if (!viewingResult.value?.resultJson) return {}
  let artifact
  try { artifact = JSON.parse(viewingResult.value.resultJson) } catch { return {} }
  const planHash = artifact?.content?.plan?.evidenceSnapshotHash
    || artifact?.plan?.evidenceSnapshotHash
    || artifact?.evidenceSnapshotHash
  return {
    evidenceSnapshotHash: artifact?.evidenceHash || planHash || '',
    documentVersion: artifact?.documentVersion || artifact?.content?.document?.version || '',
  }
})

function formatDate(v) { return v ? String(v).replace('T', ' ').slice(0, 16) : '' }
function parseFeatures(v) { try { return JSON.parse(v) || {} } catch { return {} } }
function parseSummary(v) { try { return JSON.parse(v) || {} } catch { return {} } }
function formatDatasetType(v) {
  return {
    CONTRACT_REVIEW: '风险审查',
    RISK_REVIEW: '风险审查',
    INTAKE: '合同要素提取',
    ELEMENT_EXTRACTION: '合同要素提取',
    FULFILLMENT_TIMELINE: '履约日程提取',
    TIMELINE_EXTRACTION: '履约日程提取',
    FULFILLMENT_CHECK: '履约核验',
    FULFILLMENT_VERIFICATION: '履约核验',
    COMPREHENSIVE: '综合评测',
  }[v] || v || '-'
}
function formatRuntimeEngine(v) {
  return {
    legacy: '传统流水线',
    langgraph: 'LangGraph',
    langgraph_v2: 'LangGraph v2 (试点)',
  }[v] || v || '-'
}
function formatMetric(row, key) {
  if (['QUEUED', 'PRECHECKING', 'RUNNING'].includes(row?.status)) return row.caseCount ? '计算中' : '待汇总'
  if (['FAILED', 'ENVIRONMENT_UNAVAILABLE'].includes(row?.status)) return '-'
  const value = Number(row?.[key])
  return Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : '-'
}
function evalPercent(row) {
  const summary = parseSummary(row?.summaryJson)
  const value = Number(summary.percent ?? 0)
  if (Number.isFinite(value) && value > 0) return Math.max(0, Math.min(100, Math.round(value)))
  const total = Number(row?.caseCount ?? summary.caseCount ?? 0)
  const current = Number(row?.currentCaseIndex ?? summary.completedCases ?? 0)
  if (Number.isFinite(total) && total > 0) return Math.max(0, Math.min(100, Math.round((current / total) * 100)))
  return ['COMPLETED', 'DEGRADED'].includes(row?.status) ? 100 : 0
}
function progressText(row) {
  const summary = parseSummary(row?.summaryJson)
  if (row?.status === 'QUEUED') return row.queuePosition ? `排队 #${row.queuePosition}` : '排队中'
  if (row?.status === 'PRECHECKING') return '环境检查中'
  if (row?.status === 'ENVIRONMENT_UNAVAILABLE') return '环境不可用'
  const total = Number(row?.caseCount ?? summary.caseCount ?? 0)
  const current = Number(row?.currentCaseIndex ?? summary.completedCases ?? 0)
  if (row?.status === 'RUNNING' && total > 0) return `${current}/${total} ${row.currentCaseKey || ''}`.trim()
  if (summary.infraFailedCount) return `完成，环境失败 ${summary.infraFailedCount}`
  return row.currentStep || formatStatus(row.status)
}
function formatEffectiveCases(row) {
  const summary = parseSummary(row?.summaryJson)
  const total = Number(row?.caseCount ?? summary.caseCount ?? 0)
  if (!Number.isFinite(total) || total <= 0) return '-'
  if (['QUEUED', 'PRECHECKING', 'RUNNING'].includes(row?.status)) return `${Number(row?.passedCount ?? 0)}/${total}`
  const failed = Number(summary.failedCount ?? Math.max(total - Number(row?.passedCount ?? 0), 0))
  const limited = Number(summary.limitedCount ?? (Number(summary.limitedReportRate) > 0 ? Math.round(Number(summary.limitedReportRate) * total) : 0))
  const infra = Number(summary.infraFailedCount ?? summary.infraFailedCases ?? 0)
  const valid = Math.max(0, total - (Number.isFinite(failed) ? failed : 0) - (Number.isFinite(limited) ? limited : 0) - (Number.isFinite(infra) ? infra : 0))
  return `${valid}/${total}`
}
function formatExecutedCases(row) {
  const summary = parseSummary(row?.summaryJson)
  const total = Number(row?.caseCount ?? summary.caseCount ?? 0)
  if (!Number.isFinite(total) || total <= 0) return '-'
  const executed = Number(row?.passedCount ?? summary.passedCount ?? 0)
  return `${Number.isFinite(executed) ? executed : 0}/${total}`
}
function rerankExecution(row) {
  const summary = parseSummary(row?.summaryJson)
  const methods = Array.isArray(summary.rerankActualMethods) ? summary.rerankActualMethods : []
  if (!methods.length || ['QUEUED', 'PRECHECKING', 'RUNNING'].includes(row?.status)) return { label: '', type: 'info' }
  if (methods.length === 1 && methods[0] === 'MODEL_RERANK') return { label: '模型重排序已执行', type: 'success' }
  if (methods.length === 1 && methods[0] === 'DISABLED') return { label: '重排序已关闭', type: 'info' }
  if (methods.every(method => method === 'NOT_USED')) return { label: '未触发重排序', type: 'info' }
  if (methods.includes('KEYWORD_FALLBACK') || methods.includes('MIXED')) return { label: '重排序降级为关键词', type: 'warning' }
  return { label: '混合重排序', type: 'warning' }
}
function formatStatus(v) {
  return {
    ACTIVE: '启用',
    DRAFT: '草稿',
    QUEUED: '排队中',
    PRECHECKING: '环境检查',
    RUNNING: '运行中',
    COMPLETED: '已完成',
    DEGRADED: '结果降级',
    ENVIRONMENT_UNAVAILABLE: '环境不可用',
    FAILED: '失败',
    CANCELLED: '已取消',
  }[v] || v || '-'
}
function formatAnalysisMode(v) {
  return {
    FULL: '完整分析',
    LIMITED: '范围受限',
    RULE_ONLY: '规则兜底',
    INFRA_FAILED: '环境失败',
  }[v] || v || '-'
}
function statusTagType(v) {
  return {
    COMPLETED: 'success',
    QUEUED: 'info',
    PRECHECKING: 'info',
    RUNNING: 'primary',
    DEGRADED: 'warning',
    ENVIRONMENT_UNAVAILABLE: 'danger',
    FAILED: 'danger',
    CANCELLED: 'info',
  }[v] || 'info'
}
function analysisModeTagType(v) {
  return {
    FULL: 'success',
    LIMITED: 'warning',
    RULE_ONLY: 'info',
    INFRA_FAILED: 'danger',
  }[v] || 'info'
}
function severityTagType(v) {
  return {
    HIGH: 'danger',
    MEDIUM: 'warning',
    LOW: 'info',
  }[String(v || '').toUpperCase()] || 'info'
}
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { max-width: 820px; margin: 0; color: #607184; line-height: 1.7; }

/* Trend strip */
.trend-strip { padding: 18px; background: #f8fafc; border: 1px solid #dce4ee; border-radius: 4px; }
.trend-strip h3 { font-size: 14px; color: #1f2d3d; margin: 0 0 14px; }
.trend-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.trend-card { padding: 14px; background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.trend-card strong { display: block; margin-top: 8px; color: #1f2d3d; font-size: 14px; }
.trend-metrics { display: flex; gap: 14px; margin-top: 10px; }
.trend-metrics small { color: #607184; font-size: 12px; }

/* Section actions */
.section-actions { margin-bottom: 14px; }

/* Cases panel */
.cases-panel { margin-top: 24px; padding: 18px; background: #fbfcfe; border: 1px solid #dce4ee; border-radius: 4px; }
.cases-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.cases-head h3 { margin: 0; color: #1f2d3d; font-size: 15px; }
.back-btn { margin-top: 14px; }

/* Case detail */
.contract-text-viewer {
  max-height: 300px; overflow-y: auto;
  padding: 14px; background: #f5f7fa; border: 1px solid #e4e7ed; border-radius: 4px;
  font-size: 13px; line-height: 1.8; color: #303133; white-space: normal; word-break: break-all;
}
.json-block {
  max-height: 200px; overflow-y: auto;
  padding: 12px; background: #f5f7fa; border: 1px solid #e4e7ed; border-radius: 4px;
  font-size: 12px; line-height: 1.6; color: #303133; margin: 0; white-space: pre-wrap; word-break: break-all;
}
.mono-tiny { font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace; font-size: 12px; color: #4a5b6e; }
.artifact-block { max-height: 420px; }

/* Compare */
.compare-controls { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
.compare-controls .vs { color: #909399; font-size: 15px; font-weight: 700; }

.compare-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.compare-table th { text-align: left; padding: 10px 12px; background: #f3f6fa; color: #607184; font-weight: 800; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; border-bottom: 2px solid #dce4ee; }
.compare-table td { padding: 10px 12px; border-bottom: 1px solid #eef1f5; color: #1f2d3d; }
.compare-table tr.has-diff { background: #fffbeb; }

@media (max-width: 860px) {
  .trend-grid { grid-template-columns: 1fr; }
}
</style>
