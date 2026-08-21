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
            <small v-for="metric in primaryMetrics(r).slice(0, 2)" :key="metric.key">
              {{ metric.label }} {{ taskMetricValue(r, metric.key) }}
            </small>
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
          <el-table-column prop="taskPurpose" label="任务用途" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.taskPurpose" type="warning" effect="plain" size="small">
                {{ row.taskPurpose }}
              </el-tag>
              <span v-else style="color: #a8abb2">—</span>
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
                <el-option label="首次合同识别" value="CONTRACT_INTAKE" />
                <el-option label="合同要素提取" value="CONTRACT_ELEMENT_EXTRACTION" />
                <el-option label="履约日程提取" value="TIMELINE_EXTRACTION" />
                <el-option label="履约核验" value="FULFILLMENT_CHECK" />
                <el-option label="综合评测" value="COMPREHENSIVE" />
              </el-select>
            </el-form-item>
            <el-form-item label="任务用途">
              <el-input v-model="newDataset.taskPurpose" placeholder="如 要素提取 / 履约日程 / 风险审查 / 综合" />
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
            <template v-if="isFulfillmentDataset">
              <el-alert
                title="履约核验用例会先从合同全文提取日程，再把下列独立证明材料绑定到指定节点。实际履约情况不能写入合同全文。"
                type="info" :closable="false" style="margin:0 0 16px" />
              <el-form-item label="目标日程节点">
                <el-input v-model="newCase.targetTimelineSelectorJson" type="textarea" rows="3"
                  placeholder='{"nodeType":"DELIVERY","labelContains":"交付"}' />
                <small style="color:#909399;display:block;margin-top:4px">JSON 对象。支持 nodeType、date、labelContains、conditionContains，必须唯一命中一个日程节点。</small>
              </el-form-item>
              <el-form-item label="履约证明材料">
                <el-input v-model="newCase.fulfillmentEvidenceJson" type="textarea" rows="5"
                  placeholder='[{"fileName":"交付清单.txt","content":"实际已交付..."}]' />
                <small style="color:#909399;display:block;margin-top:4px">JSON 数组，每项需要 content；评测会作为独立履约证据上传。</small>
              </el-form-item>
              <el-form-item label="预期 AI 判断">
                <el-input v-model="newCase.expectedJudgementsJson" type="textarea" rows="4"
                  placeholder='[{"requirementContains":"交付","proofStatus":"SUPPORTED"}]' />
              </el-form-item>
              <el-form-item label="预期人工结论">
                <el-select v-model="newCase.expectedManualResult" style="width:100%" placeholder="选择受控终审结论">
                  <el-option label="履约满足" value="SATISFIED" />
                  <el-option label="不满足" value="NOT_SATISFIED" />
                  <el-option label="保持待处理" value="PENDING" />
                </el-select>
              </el-form-item>
            </template>
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
              <el-descriptions-item label="金标状态" :span="1">
                <el-tag :type="annotationTagType(viewingCase.annotationStatus)" effect="plain" size="small">{{ annotationLabel(viewingCase.annotationStatus) }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="必须引用合同" :span="1">{{ viewingCase.mustHaveContractCitation ? '是' : '否' }}</el-descriptions-item>
              <el-descriptions-item label="必须引用政策" :span="1">{{ viewingCase.mustHavePolicyCitation ? '是' : '否' }}</el-descriptions-item>
            </el-descriptions>
            <h4 style="margin:16px 0 8px;color:#303133">合同全文</h4>
            <div class="contract-text-viewer" v-html="renderedContractText()"></div>
            <h4 style="margin:16px 0 8px;color:#303133">预期发现 (expectedFindingsJson)</h4>
            <pre class="json-block">{{ formatJson(viewingCase.expectedFindingsJson) }}</pre>
            <h4 style="margin:16px 0 8px;color:#303133">任务标准答案 (expectedOutputJson)</h4>
            <pre class="json-block">{{ formatJson(viewingCase.expectedOutputJson) }}</pre>
            <template v-if="viewingCase.candidateLabelJson">
              <h4 style="margin:16px 0 8px;color:#303133">LLM 候选金标</h4>
              <pre class="json-block">{{ formatJson(viewingCase.candidateLabelJson) }}</pre>
            </template>
            <h4 style="margin:16px 0 8px;color:#303133">不应发现 (shouldNotFindJson)</h4>
            <pre class="json-block">{{ formatJson(viewingCase.shouldNotFindJson) }}</pre>
            <template v-if="isFulfillmentCase(viewingCase)">
              <h4 style="margin:16px 0 8px;color:#303133">目标日程节点</h4>
              <pre class="json-block">{{ formatJson(viewingCase.targetTimelineSelectorJson) }}</pre>
              <h4 style="margin:16px 0 8px;color:#303133">独立履约证明</h4>
              <pre class="json-block">{{ formatJson(viewingCase.fulfillmentEvidenceJson) }}</pre>
              <h4 style="margin:16px 0 8px;color:#303133">预期 AI 判断 / 人工结论</h4>
              <pre class="json-block">{{ formatJson(viewingCase.expectedJudgementsJson) }}\n人工：{{ viewingCase.expectedManualResult || '未设置' }}</pre>
            </template>
          </template>
          <template #footer>
            <el-button v-if="viewingCase?.annotationStatus !== 'APPROVED'" type="success" @click="approveCandidateLabel">确认候选金标</el-button>
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
          <el-table-column label="金标状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="annotationTagType(row.annotationStatus)" effect="plain">{{ annotationLabel(row.annotationStatus) }}</el-tag>
            </template>
          </el-table-column>
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
        <div class="run-filters" aria-label="评测记录筛选">
          <div class="run-filter-group">
            <span class="run-filter-label">Runtime</span>
            <el-checkbox-group v-model="runFilters.runtime" class="run-filter-options">
              <el-checkbox v-for="option in runFilterOptions.runtime" :key="option.value" :label="option.value">
                {{ option.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <div class="run-filter-group">
            <span class="run-filter-label">功能组件</span>
            <el-checkbox-group v-model="runFilters.component" class="run-filter-options">
              <el-checkbox v-for="option in runFilterOptions.component" :key="option.value" :label="option.value">
                {{ option.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <div class="run-filter-group">
            <span class="run-filter-label">状态</span>
            <el-checkbox-group v-model="runFilters.status" class="run-filter-options">
              <el-checkbox v-for="option in runFilterOptions.status" :key="option.value" :label="option.value">
                {{ option.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <div class="run-filter-group">
            <span class="run-filter-label">发布门禁</span>
            <el-checkbox-group v-model="runFilters.gate" class="run-filter-options">
              <el-checkbox v-for="option in runFilterOptions.gate" :key="option.value" :label="option.value">
                {{ option.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <div class="run-filter-actions">
            <span class="run-filter-count">显示 {{ filteredRuns.length }} / {{ runs.length }}</span>
            <el-button v-if="hasRunFilters" link type="primary" @click="clearRunFilters">清除筛选</el-button>
            <el-button size="small" type="warning" plain :loading="recomputingGates" @click="recomputeGates">
              重算评分与门禁
            </el-button>
          </div>
        </div>

        <el-table :data="filteredRuns" stripe v-if="filteredRuns.length">
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
          <el-table-column prop="statusLabel" label="运行状态" width="100" align="center">
            <template #default="{ row }">
              <el-tooltip v-if="stopReason(row)" :content="stopReason(row)" placement="top">
                <el-tag type="warning" effect="plain" size="small">部分（中止）</el-tag>
              </el-tooltip>
              <template v-else>{{ row.statusLabel || formatStatus(row.status) }}</template>
            </template>
          </el-table-column>
          <el-table-column label="质量状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="qualityTagType(row)" effect="plain" size="small">{{ qualityLabel(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="金标状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="goldTagType(row)" effect="plain" size="small">{{ goldLabel(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="发布状态" width="100" align="center">
            <template #default="{ row }">
              <el-tooltip v-if="gateIssueText(row)" :content="gateIssueText(row)" placement="top">
                <el-tag :type="gateTagType(row)" effect="plain" size="small">{{ gateLabel(row) }}</el-tag>
              </el-tooltip>
              <el-tag v-else :type="gateTagType(row)" effect="plain" size="small">{{ gateLabel(row) }}</el-tag>
            </template>
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
          <el-table-column label="核心指标" min-width="240" align="center">
            <template #default="{ row }">
              <div class="task-metric-list">
                <span v-for="metric in primaryMetrics(row).slice(0, 3)" :key="metric.key">
                  {{ metric.label }} {{ taskMetricValue(row, metric.key) }}
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="P95（秒）" width="90" align="center">
            <template #default="{ row }">
              <span v-if="operationValue(row, 'latencyP95Ms') !== null">{{ formatLatency(operationValue(row, 'latencyP95Ms')) }}</span>
              <span v-else class="muted">未观测</span>
            </template>
          </el-table-column>
          <el-table-column label="Token" width="110" align="center">
            <template #default="{ row }">
              <span v-if="operationValue(row, 'tokenInputTotal') !== null || operationValue(row, 'tokenOutputTotal') !== null">
                {{ formatTokens(operationValue(row, 'tokenInputTotal'), operationValue(row, 'tokenOutputTotal')) }}
              </span>
              <span v-else class="muted">未观测</span>
            </template>
          </el-table-column>
          <el-table-column label="成本" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="operationValue(row, 'costStatus') === 'AVAILABLE'" type="success" effect="plain" size="small">
                {{ formatCost(operationValue(row, 'estimatedCost'), operationValue(row, 'costCurrency')) }}
              </el-tag>
              <el-tooltip v-else content="未配置价格或 Token 遥测不可用">
                <el-tag type="info" effect="plain" size="small">不可用</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="140">
            <template #default="{ row }">{{ formatDate(row.startedAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="210" align="center">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="viewRunDetail(row.id)">详情</el-button>
              <el-button v-if="canPromote(row)" size="small" type="success" @click="promoteRun(row)">设为基线</el-button>
              <el-tag v-else-if="row.isProductionBaseline" type="success" effect="plain" size="small">生产基线</el-tag>
              <el-button size="small" type="danger" @click="deleteRun(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else :description="runs.length ? '没有符合筛选条件的评测记录' : '暂无评测记录'" :image-size="64" />
      </el-tab-pane>

      <!-- ═══ Run detail dialog ═══ -->
      <el-dialog v-model="showRunDetail" title="评测运行详情" width="92%" top="3vh" destroy-on-close>
        <template v-if="viewingRun && !viewingResult">
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="Run ID">{{ viewingRun.id }}</el-descriptions-item>
            <el-descriptions-item label="运行状态">
              <el-tag size="small" :type="statusTagType(viewingRun.status)">{{ viewingRun.statusLabel || formatStatus(viewingRun.status) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item v-if="stopReason(viewingRun)" label="中止原因" :span="2">
              <span style="color:#e6a23c">{{ stopReason(viewingRun) }}</span>
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
            <el-descriptions-item v-for="metric in primaryMetrics(viewingRun)" :key="metric.key" :label="metric.label">
              {{ taskMetricValue(viewingRun, metric.key) }}
            </el-descriptions-item>
            <el-descriptions-item label="质量状态">
              <el-tag :type="qualityTagType(viewingRun)" effect="plain" size="small">{{ qualityLabel(viewingRun) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="金标状态">
              <el-tag :type="goldTagType(viewingRun)" effect="plain" size="small">{{ goldLabel(viewingRun) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="发布状态" :span="2">
              <div class="gate-detail">
                <el-tag :type="gateTagType(viewingRun)" effect="plain" size="small">{{ gateLabel(viewingRun) }}</el-tag>
                <span v-if="gateIssueText(viewingRun)" class="gate-issues">{{ gateIssueText(viewingRun) }}</span>
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="生产基线" :span="2">
              <el-tag v-if="viewingRun.isProductionBaseline" type="success" effect="plain" size="small">当前数据集基线</el-tag>
              <span v-else class="muted">未设为基线</span>
              <small v-if="viewingRun.promotedAt" class="baseline-time">{{ formatDate(viewingRun.promotedAt) }}</small>
            </el-descriptions-item>
            <el-descriptions-item label="P50 / P95">
              {{ formatLatency(operationValue(viewingRun, 'latencyP50Ms')) }} / {{ formatLatency(operationValue(viewingRun, 'latencyP95Ms')) }}
            </el-descriptions-item>
            <el-descriptions-item label="Token 总量">
              {{ formatTokens(operationValue(viewingRun, 'tokenInputTotal'), operationValue(viewingRun, 'tokenOutputTotal')) }}
            </el-descriptions-item>
            <el-descriptions-item label="估算成本">
              {{ operationValue(viewingRun, 'costStatus') === 'AVAILABLE'
                ? formatCost(operationValue(viewingRun, 'estimatedCost'), operationValue(viewingRun, 'costCurrency'))
                : '不可用（缺少价格或 Token 遥测）' }}
            </el-descriptions-item>
            <el-descriptions-item label="执行栈" :span="2">
              <span class="mono-tiny">{{ formatExecutionStack(viewingRun) }}</span>
            </el-descriptions-item>
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
            <el-table-column v-for="metric in primaryMetrics(viewingRun).slice(0, 3)" :key="metric.key" :label="metric.short" width="100" align="center">
              <template #default="{ row }">{{ taskMetricValue(row, metric.key) }}</template>
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
            <el-descriptions-item v-for="metric in primaryMetrics(viewingRun)" :key="metric.key" :label="metric.label">
              {{ taskMetricValue(viewingResult, metric.key) }}
            </el-descriptions-item>
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

          <h4 style="margin:12px 0 8px;color:#303133">
            实际结果 · {{ formatDatasetType(resultTaskType) }} ({{ actualResultCount }})
          </h4>

          <!-- 风险审查保留原有发现表格。 -->
          <template v-if="resultTaskType === 'CONTRACT_REVIEW'">
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
          </template>

          <!-- 履约日程使用 nodes，而不是风险 findings。 -->
          <template v-else-if="resultTaskType === 'TIMELINE_EXTRACTION'">
            <el-table :data="actualTimelineNodes" stripe size="small" v-if="actualTimelineNodes.length">
              <el-table-column prop="nodeType" label="节点类型" width="110" />
              <el-table-column prop="label" label="节点" min-width="150" show-overflow-tooltip />
              <el-table-column label="日期 / 条件" min-width="190" show-overflow-tooltip>
                <template #default="{ row }">{{ row.date || row.condition || '-' }}</template>
              </el-table-column>
              <el-table-column prop="responsibleParty" label="责任方" width="100" />
              <el-table-column prop="businessMeaning" label="业务含义" min-width="220" show-overflow-tooltip />
              <el-table-column label="原文" width="90" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.citation?.quote" size="small" effect="plain" type="success">已引用</el-tag>
                  <span v-else class="muted">-</span>
                </template>
              </el-table-column>
            </el-table>
          </template>

          <!-- 合同要素同时展示模型要素和合同画像字段。 -->
          <template v-else-if="['CONTRACT_INTAKE', 'CONTRACT_ELEMENT_EXTRACTION'].includes(resultTaskType)">
            <el-table :data="actualElementRows" stripe size="small" v-if="actualElementRows.length">
              <el-table-column prop="category" label="类别" width="130" show-overflow-tooltip />
              <el-table-column prop="key" label="字段" width="170" show-overflow-tooltip />
              <el-table-column label="提取值" min-width="280" show-overflow-tooltip>
                <template #default="{ row }">{{ formatDisplayValue(row.value) }}</template>
              </el-table-column>
              <el-table-column label="引用" width="90" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.citations?.length || row.citation" size="small" effect="plain" type="success">已引用</el-tag>
                  <span v-else class="muted">-</span>
                </template>
              </el-table-column>
            </el-table>
          </template>

          <!-- 履约核验展示履约要求、证据状态、AI 建议和人工结论。 -->
          <template v-else-if="resultTaskType === 'FULFILLMENT_CHECK'">
            <el-table :data="actualFulfillmentRequirements" stripe size="small" v-if="actualFulfillmentRequirements.length">
              <el-table-column prop="requirement" label="履约要求" min-width="260" show-overflow-tooltip />
              <el-table-column prop="proofStatus" label="证据状态" width="130" />
              <el-table-column prop="judgement" label="AI 判断" width="130" />
              <el-table-column label="AI 建议" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">{{ row.aiSuggestion?.conclusion || row.aiSuggestion?.status || '-' }}</template>
              </el-table-column>
              <el-table-column label="证据" width="90" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.evidenceSnapshot || row.evidenceCitationIds?.length || row.contractCitationIds?.length" size="small" effect="plain" type="success">已提供</el-tag>
                  <span v-else class="muted">无</span>
                </template>
              </el-table-column>
            </el-table>
          </template>

          <!-- 综合评测按阶段展示，避免把不同任务强行合并为风险发现。 -->
          <template v-else-if="resultTaskType === 'COMPREHENSIVE'">
            <div v-for="section in actualStageSections" :key="section.key" class="actual-stage-section">
              <h5>{{ section.label }} ({{ section.rows.length }})</h5>
              <el-table :data="section.rows" stripe size="small">
                <el-table-column prop="type" label="类型" width="130" />
                <el-table-column prop="title" label="结果" min-width="220" show-overflow-tooltip />
                <el-table-column prop="detail" label="详情" min-width="260" show-overflow-tooltip />
                <el-table-column prop="status" label="状态" width="130" show-overflow-tooltip />
              </el-table>
            </div>
          </template>

          <el-empty v-if="!actualResultCount" description="该结果没有可展示的任务输出" :image-size="48" />

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
        <!-- v1 基线 / 迁移版本 / 未来版本聚合对照（PRD Phase 8 task 7） -->
        <div class="version-board" v-if="versionBoard.length">
          <h4>版本维度汇总（已完成评测，按运行时/图/模型/提示词版本聚合）</h4>
          <el-table :data="versionBoard" stripe size="small">
            <el-table-column label="版本" min-width="220">
              <template #default="{ row }">
                <el-tag :type="row.runtimeEngine === 'legacy' ? 'info' : 'success'" effect="plain" size="small">
                  {{ row.versionLabel }}
                </el-tag>
                <span v-if="row.llmModel" style="margin-left:6px;font-size:12px;color:#8b9aaa">
                  {{ row.llmModel }} · {{ row.promptVersion }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="runCount" label="Run 数" width="80" align="center" />
            <el-table-column label="平均召回" width="100" align="center">
              <template #default="{ row }">{{ (row.avgHighRiskRecall * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="平均双引用" width="100" align="center">
              <template #default="{ row }">{{ (row.avgDualCitationRate * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="平均误报率" width="100" align="center">
              <template #default="{ row }">{{ (row.avgFalsePositiveRate * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="Schema 有效" width="110" align="center">
              <template #default="{ row }">{{ (row.avgSchemaValidRate * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="最近完成" width="170">
              <template #default="{ row }">{{ formatDate(row.lastFinishedAt) }}</template>
            </el-table-column>
          </el-table>
        </div>

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
              <th v-for="metric in compareMetrics" :key="`head1-${metric.key}`">{{ metric.short }}1</th>
              <th v-for="metric in compareMetrics" :key="`head2-${metric.key}`">{{ metric.short }}2</th>
              <th>模式1</th>
              <th>模式2</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in compareDiffs" :key="d.caseId" :class="{ 'has-diff': compareMetrics.some(metric => taskMetricValue(d, metric.key, 1) !== taskMetricValue(d, metric.key, 2)) || d.mode1 !== d.mode2 }">
              <td>{{ d.caseTitle }}</td>
              <td v-for="metric in compareMetrics" :key="`left-${metric.key}`">{{ taskMetricValue(d, metric.key, 1) }}</td>
              <td v-for="metric in compareMetrics" :key="`right-${metric.key}`">{{ taskMetricValue(d, metric.key, 2) }}</td>
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
const runFilters = ref({ runtime: [], component: [], status: [], gate: [] })
const trend = ref([])
const versionBoard = ref([])
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
const newCase = ref({ caseKey: '', title: '', contractText: '', expectedFindingsJson: '[]', shouldNotFindJson: '[]', expectedCitationCount: 0, scenario: '', industry: '', difficulty: '', noiseLevel: '', mustHaveContractCitation: 0, mustHavePolicyCitation: 0, fulfillmentEvidenceJson: '[]', targetTimelineSelectorJson: '{}', expectedJudgementsJson: '[]', expectedManualResult: '' })
const isFulfillmentDataset = computed(() => ['FULFILLMENT_CHECK', 'FULFILLMENT_VERIFICATION'].includes((selectedDataset.value?.contractType || '').toUpperCase()))
const isFulfillmentCase = (item) => ['FULFILLMENT_CHECK', 'FULFILLMENT_VERIFICATION'].includes((item?.contractType || '').toUpperCase())
const showStartRun = ref(false)
const startRunDs = ref(null)
const startRunRuntime = ref('legacy')
// Legacy 引擎无提取/日程任务的实现，这些数据集只能跑 LangGraph
const legacyBlocked = computed(() => {
  const t = (startRunDs.value?.contractType || '').toUpperCase()
  return ['CONTRACT_INTAKE', 'INTAKE', 'ELEMENT_EXTRACTION', 'CONTRACT_ELEMENT_EXTRACTION', 'FULFILLMENT_TIMELINE', 'TIMELINE_EXTRACTION', 'FULFILLMENT_CHECK', 'FULFILLMENT_VERIFICATION'].includes(t)
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
const recomputingGates = ref(false)

const taskMetricDefinitions = {
  CONTRACT_INTAKE: [
    { key: 'fieldAccuracy', label: '基础字段准确率', short: '字段准确' },
    { key: 'partyRoleAccuracy', label: '主体角色准确率', short: '主体角色' },
    { key: 'amountAccuracy', label: '金额准确率', short: '金额准确' },
    { key: 'dateAccuracy', label: '日期准确率', short: '日期准确' },
    { key: 'contractTitleAccuracy', label: '合同标题准确率', short: '标题准确' },
    { key: 'citationCoverage', label: '原文引用覆盖率', short: '引用覆盖' },
    { key: 'schemaValidRate', label: 'Schema 有效率', short: 'Schema' },
  ],
  CONTRACT_ELEMENT_EXTRACTION: [
    { key: 'fieldRecall', label: '要素召回率', short: '要素召回' },
    { key: 'valueAccuracy', label: '要素值准确率', short: '值准确' },
    { key: 'citationCoverage', label: '原文引用覆盖率', short: '引用覆盖' },
    { key: 'hallucinationRate', label: '幻觉率', short: '幻觉率', inverse: true },
    { key: 'schemaValidRate', label: 'Schema 有效率', short: 'Schema' },
  ],
  TIMELINE_EXTRACTION: [
    { key: 'nodeRecall', label: '节点召回率', short: '节点召回' },
    { key: 'dateAccuracy', label: '日期准确率', short: '日期准确' },
    { key: 'conditionRecognitionRate', label: '条件事件识别率', short: '条件识别' },
    { key: 'responsiblePartyCoverage', label: '责任方覆盖率', short: '责任方' },
    { key: 'schemaValidRate', label: 'Schema 有效率', short: 'Schema' },
  ],
  CONTRACT_REVIEW: [
    { key: 'riskRecall', label: '风险召回率', short: '风险召回' },
    { key: 'citationCoverage', label: '双引用覆盖率', short: '双引用' },
    { key: 'falsePositiveRate', label: '误报率', short: '误报率', inverse: true },
    { key: 'severityAccuracy', label: '严重性准确率', short: '严重性' },
    { key: 'schemaValidRate', label: 'Schema 有效率', short: 'Schema' },
  ],
  FULFILLMENT_CHECK: [
    { key: 'requirementRecall', label: '履约要求召回率', short: '要求召回' },
    { key: 'proofStatusAccuracy', label: '证据状态准确率', short: '证据状态' },
    { key: 'judgementAccuracy', label: 'AI 判断准确率', short: '判断准确' },
    { key: 'aiSuggestionAccuracy', label: 'AI 建议准确率', short: 'AI 建议' },
    { key: 'restraintRate', label: '证据不足克制率', short: '克制率' },
    { key: 'humanResultMatch', label: '人工终审一致率', short: '人工一致' },
    { key: 'aiAutoConfirmViolations', label: 'AI 自动终审违规', short: '自动终审', count: true },
  ],
  COMPREHENSIVE: [
    { key: 'workflowCompletionRate', label: '工作流完成率', short: '完成率' },
    { key: 'crossStageConsistency', label: '跨阶段一致性', short: '跨阶段' },
    { key: 'snapshotReuseRate', label: '快照复用率', short: '快照复用' },
    { key: 'schemaValidRate', label: 'Schema 有效率', short: 'Schema' },
  ],
}

const runFilterOptions = computed(() => {
  const runtimeValues = [...new Set(runs.value.map(row => String(row.runtimeEngine || '')).filter(Boolean))]
  const statusValues = [...new Set(runs.value.map(row => String(row.status || '')).filter(Boolean))]
  const gateValues = [...new Set(runs.value.map(row => gateFilterValue(row)))]
  return {
    runtime: runtimeValues.map(value => ({ value, label: formatRuntimeEngine(value) })),
    component: [
      { value: 'MODEL', label: '指定模型' },
      { value: 'PROMPT', label: '指定提示词' },
      { value: 'RERANK_REQUESTED', label: '请求重排序' },
      { value: 'RERANK_DISABLED', label: '无重排序' },
      { value: 'RERANK_MODEL', label: '模型重排序已执行' },
      { value: 'RERANK_FALLBACK', label: '重排序降级' },
      { value: 'TARGETED_RETRIEVAL', label: '定向检索' },
      { value: 'COVERAGE_REFLECTION', label: '覆盖反思' },
    ],
    status: statusValues.map(value => ({ value, label: formatStatus(value) })),
    gate: gateValues.map(value => ({ value, label: gateFilterLabel(value) })),
  }
})
const filteredRuns = computed(() => runs.value.filter(row => {
  const selected = runFilters.value
  const runtimeMatch = !selected.runtime.length || selected.runtime.includes(String(row.runtimeEngine || ''))
  const statusMatch = !selected.status.length || selected.status.includes(String(row.status || ''))
  const gateMatch = !selected.gate.length || selected.gate.includes(gateFilterValue(row))
  const componentMatch = !selected.component.length || selected.component.some(value => hasRunComponent(row, value))
  return runtimeMatch && statusMatch && gateMatch && componentMatch
}))
const hasRunFilters = computed(() => Object.values(runFilters.value).some(values => values.length))

onMounted(() => { loadAll() })

async function loadAll() {
  try { datasets.value = (await api.get('/api/admin/eval/datasets')).data.data || [] } catch {}
  try { runs.value = (await api.get('/api/admin/eval/runs')).data.data || [] } catch {}
  try { trend.value = (await api.get('/api/admin/eval/metrics/trend')).data.data || [] } catch {}
  try { versionBoard.value = (await api.get('/api/admin/eval/versions/comparison')).data.data || [] } catch {}
}

async function recomputeGates() {
  recomputingGates.value = true
  try {
    const response = await api.post('/api/admin/eval/runs/recompute-gates', {})
    ElMessage.success(`已重算 ${response.data?.data?.recomputed || 0} 个评测运行，不会重新执行 Agent`)
    await loadAll()
    if (viewingRun.value?.id) {
      const refreshed = await api.get(`/api/admin/eval/runs/${viewingRun.value.id}`)
      viewingRun.value = refreshed.data.data || viewingRun.value
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '重算失败')
  } finally {
    recomputingGates.value = false
  }
}

async function createDataset() {
  try {
    await api.post('/api/admin/eval/datasets', newDataset.value)
    ElMessage.success('数据集已创建')
    showCreateDataset.value = false
    newDataset.value = { name: '', version: 'v1', contractType: 'CONTRACT_REVIEW', taskPurpose: '', description: '' }
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

function canPromote(row) {
  return !row?.isProductionBaseline
    && row?.status === 'COMPLETED'
    && releaseGate(row)?.status === 'PASSED'
}

async function promoteRun(row) {
  try {
    await ElMessageBox.confirm(
      `Run #${row.id} 将成为数据集 ${row.datasetName} v${row.datasetVersion} 的生产基线，原基线会保留但取消生效。继续？`,
      '确认设置生产基线',
      { type: 'warning' },
    )
  } catch { return }
  try {
    await api.post(`/api/admin/eval/runs/${row.id}/promote`)
    ElMessage.success('已设置为生产基线')
    await loadAll()
    if (viewingRun.value?.id === row.id) {
      const refreshed = await api.get(`/api/admin/eval/runs/${row.id}`)
      viewingRun.value = refreshed.data.data || viewingRun.value
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '设置基线失败')
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
      fulfillmentEvidenceJson: newCase.value.fulfillmentEvidenceJson,
      targetTimelineSelectorJson: newCase.value.targetTimelineSelectorJson,
      expectedJudgementsJson: newCase.value.expectedJudgementsJson,
      expectedManualResult: newCase.value.expectedManualResult,
    })
    ElMessage.success('用例已添加')
    showAddCase.value = false
    newCase.value = { caseKey: '', title: '', contractText: '', expectedFindingsJson: '[]', shouldNotFindJson: '[]', expectedCitationCount: 0, scenario: '', industry: '', difficulty: '', noiseLevel: '', mustHaveContractCitation: 0, mustHavePolicyCitation: 0, fulfillmentEvidenceJson: '[]', targetTimelineSelectorJson: '{}', expectedJudgementsJson: '[]', expectedManualResult: '' }
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

async function approveCandidateLabel() {
  if (!viewingCase.value?.id) return
  try {
    await ElMessageBox.confirm('确认后该标准答案可参与发布门禁。请确保已核对合同原文和候选内容。', '确认金标', { type: 'warning' })
    await api.patch(`/api/admin/eval/cases/${viewingCase.value.id}/annotation`, {
      annotationStatus: 'APPROVED',
      expectedOutputJson: viewingCase.value.expectedOutputJson || '',
    })
    viewingCase.value.annotationStatus = 'APPROVED'
    ElMessage.success('已确认金标')
    if (selectedDataset.value) viewCases(selectedDataset.value)
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '确认失败')
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

const resultArtifact = computed(() => {
  if (!viewingResult.value?.resultJson) return {}
  try {
    const parsed = JSON.parse(viewingResult.value.resultJson)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
})

const resultTaskType = computed(() => benchmarkTaskType(viewingResult.value, viewingRun.value))

function resultStage(key) {
  const stages = resultArtifact.value?.evaluationStages
  const stage = stages && typeof stages === 'object' ? stages[key] : null
  return stage && typeof stage === 'object' ? stage : resultArtifact.value
}

const actualFindings = computed(() => {
  const root = resultArtifact.value
  if (Array.isArray(root?.findings)) return root.findings
  const stageFindings = resultStage('CONTRACT_REVIEW')?.findings
  return Array.isArray(stageFindings) ? stageFindings : []
})

const actualTimelineNodes = computed(() => {
  const nodes = resultStage('TIMELINE_EXTRACTION')?.nodes
  return Array.isArray(nodes) ? nodes : []
})

const actualElementRows = computed(() => {
  const stage = resultStage('CONTRACT_ELEMENT_EXTRACTION')
  const rows = []
  for (const element of Array.isArray(stage?.elements) ? stage.elements : []) {
    if (!element || typeof element !== 'object') continue
    rows.push({
      category: element.category || '合同要素',
      key: element.elementKey || element.key || element.label || '-',
      value: element.normalizedValue ?? element.rawValue ?? element.value ?? '-',
      citations: element.citations,
      citation: element.citation,
    })
  }
  const profile = stage?.contractProfile || {}
  const profileFields = [
    ...(Array.isArray(profile.baseFields) ? profile.baseFields : []),
    ...(Array.isArray(profile.groups) ? profile.groups.flatMap(group => group?.fields || []) : []),
  ]
  for (const field of profileFields) {
    if (!field || typeof field !== 'object') continue
    rows.push({
      category: field.category || '合同画像',
      key: field.key || field.elementKey || field.label || '-',
      value: field.value ?? field.displayValue ?? field.normalizedValue ?? '-',
      citations: field.citations,
      citation: field.citation,
    })
  }
  return rows
})

const actualFulfillmentRequirements = computed(() => {
  const stage = resultStage('FULFILLMENT_CHECK')
  const content = stage?.content && typeof stage.content === 'object' ? stage.content : {}
  const requirements = stage?.requirements || content.requirements
  return Array.isArray(requirements) ? requirements : []
})

function comprehensiveRows(key, stage) {
  if (key === 'CONTRACT_REVIEW') {
    return (Array.isArray(stage?.findings) ? stage.findings : []).map(item => ({
      type: item.severity || '风险发现',
      title: item.title || item.oneLineSummary || '-',
      detail: item.description || item.riskExplanation || '-',
      status: item.riskDimension || item.domainKey || '-',
    }))
  }
  if (key === 'TIMELINE_EXTRACTION') {
    return (Array.isArray(stage?.nodes) ? stage.nodes : []).map(item => ({
      type: item.nodeType || '日程节点',
      title: item.label || '-',
      detail: item.date || item.condition || item.businessMeaning || '-',
      status: item.responsibleParty || '-',
    }))
  }
  if (key === 'CONTRACT_ELEMENT_EXTRACTION') {
    const elements = Array.isArray(stage?.elements) ? stage.elements : []
    const profile = stage?.contractProfile || {}
    const elementRows = elements.map(item => ({
      type: item.category || '合同要素',
      title: item.elementKey || item.key || item.label || '-',
      detail: formatDisplayValue(item.normalizedValue ?? item.rawValue ?? item.value),
      status: item.citations?.length || item.citation ? '已引用' : '未引用',
    }))
    const profileFields = [
      ...(Array.isArray(profile.baseFields) ? profile.baseFields : []),
      ...(Array.isArray(profile.groups) ? profile.groups.flatMap(group => group?.fields || []) : []),
    ]
    const profileRows = profileFields.map(item => ({
      type: '合同画像',
      title: item.key || item.label || '-',
      detail: formatDisplayValue(item.value ?? item.displayValue ?? item.normalizedValue),
      status: item.citations?.length || item.citation ? '已引用' : '未引用',
    }))
    return [...elementRows, ...profileRows]
  }
  if (key === 'FULFILLMENT_CHECK') {
    const content = stage?.content && typeof stage.content === 'object' ? stage.content : {}
    const requirements = stage?.requirements || content.requirements
    return (Array.isArray(requirements) ? requirements : []).map(item => ({
      type: item.proofStatus || '履约要求',
      title: item.requirement || '-',
      detail: item.aiSuggestion?.conclusion || item.aiSuggestion?.status || '-',
      status: item.judgement || content.manualResult || '-',
    }))
  }
  return []
}

const actualStageSections = computed(() => {
  if (resultTaskType.value !== 'COMPREHENSIVE') return []
  const labels = {
    CONTRACT_ELEMENT_EXTRACTION: '合同要素',
    TIMELINE_EXTRACTION: '履约日程',
    CONTRACT_REVIEW: '风险审查',
    FULFILLMENT_CHECK: '履约核验',
  }
  const stages = resultArtifact.value?.evaluationStages
  if (!stages || typeof stages !== 'object') return []
  return Object.entries(labels)
    .map(([key, label]) => ({ key, label, rows: comprehensiveRows(key, stages[key]) }))
    .filter(section => section.rows.length)
})

const actualResultCount = computed(() => {
  if (resultTaskType.value === 'CONTRACT_REVIEW') return actualFindings.value.length
  if (resultTaskType.value === 'TIMELINE_EXTRACTION') return actualTimelineNodes.value.length
  if (['CONTRACT_INTAKE', 'CONTRACT_ELEMENT_EXTRACTION'].includes(resultTaskType.value)) return actualElementRows.value.length
  if (resultTaskType.value === 'FULFILLMENT_CHECK') return actualFulfillmentRequirements.value.length
  if (resultTaskType.value === 'COMPREHENSIVE') {
    return actualStageSections.value.reduce((total, section) => total + section.rows.length, 0)
  }
  return 0
})

function formatDisplayValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value, null, 0)
  return String(value)
}

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
function parseSummary(v) {
  if (v && typeof v === 'object') return v
  try { return JSON.parse(v) || {} } catch { return {} }
}
function benchmarkTaskType(row, fallbackRow = null) {
  const summary = parseSummary(row?.summaryJson)
  const raw = summary.benchmarkTaskType
    || row?.benchmarkTaskType
    || row?.contractType
    || fallbackRow?.benchmarkTaskType
    || fallbackRow?.contractType
    || 'CONTRACT_REVIEW'
  return {
    INTAKE: 'CONTRACT_ELEMENT_EXTRACTION',
    ELEMENT_EXTRACTION: 'CONTRACT_ELEMENT_EXTRACTION',
    FULFILLMENT_TIMELINE: 'TIMELINE_EXTRACTION',
    RISK_REVIEW: 'CONTRACT_REVIEW',
    FULFILLMENT_VERIFICATION: 'FULFILLMENT_CHECK',
  }[String(raw).toUpperCase()] || String(raw).toUpperCase()
}
function primaryMetrics(row) {
  return taskMetricDefinitions[benchmarkTaskType(row)] || taskMetricDefinitions.CONTRACT_REVIEW
}
function metricMap(row, side = 0) {
  if (side) return row?.[`taskMetrics${side}`] || {}
  if (row?.taskMetrics && typeof row.taskMetrics === 'object') return row.taskMetrics
  const summary = parseSummary(row?.summaryJson)
  return summary.taskMetrics || {}
}
function taskMetricValue(row, key, side = 0) {
  const direct = metricMap(row, side)[key]
  const legacy = {
    riskRecall: side ? row?.[`recall${side}`] : row?.highRiskRecall ?? row?.highRecall,
    citationCoverage: side ? row?.[`dualCite${side}`] : row?.dualCitationRate,
    falsePositiveRate: side ? undefined : row?.falsePositiveRate,
    schemaValidRate: row?.schemaValidRate,
  }[key]
  const value = direct ?? legacy
  if (value === undefined || value === null || value === '') return '未观测'
  const metric = primaryMetrics(side ? (side === 1 ? compareRun1.value : compareRun2.value) : row).find(item => item.key === key)
  if (metric?.count) return String(value)
  const number = Number(value)
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : '未观测'
}
const compareRun1 = computed(() => runs.value.find(row => row.id === compareId1.value) || null)
const compareRun2 = computed(() => runs.value.find(row => row.id === compareId2.value) || null)
const compareMetrics = computed(() => primaryMetrics(compareRun1.value || compareRun2.value).slice(0, 3))
function annotationLabel(value) {
  return { APPROVED: '已确认', CANDIDATE: '候选金标', PROVISIONAL: '待确认' }[String(value || 'PROVISIONAL').toUpperCase()] || '待确认'
}
function annotationTagType(value) {
  return { APPROVED: 'success', CANDIDATE: 'warning', PROVISIONAL: 'info' }[String(value || 'PROVISIONAL').toUpperCase()] || 'info'
}
function releaseGate(row) {
  const gate = parseSummary(row?.summaryJson).releaseGate
  return gate && typeof gate === 'object' ? gate : null
}
function gateValue(row, key) {
  const gate = releaseGate(row)
  if (gate?.[key]) return String(gate[key]).toUpperCase()
  if (key === 'executionStatus') return String(row?.status || '').toUpperCase() || 'UNKNOWN'
  if (key === 'qualityStatus') {
    if (gate?.status === 'PASSED') return 'PASSED'
    if (gate?.status === 'FAILED') return 'FAILED'
    return 'NOT_EVALUATED'
  }
  if (key === 'goldStatus') return gate ? 'LEGACY' : 'UNKNOWN'
  if (key === 'publishStatus') {
    if (gate?.status === 'PASSED') return 'PUBLISHABLE'
    if (gate?.status === 'FAILED' || gate?.status === 'BLOCKED') return 'BLOCKED'
    return 'UNKNOWN'
  }
  return 'UNKNOWN'
}
function qualityLabel(row) {
  return { PASSED: '质量达标', FAILED: '质量未达标', NOT_EVALUATED: '未评估' }[gateValue(row, 'qualityStatus')] || '未评估'
}
function goldLabel(row) {
  return { APPROVED: '金标已确认', PARTIAL: '部分确认', PROVISIONAL: '候选金标', LEGACY: '历史口径' }[gateValue(row, 'goldStatus')] || '未计算'
}
function qualityTagType(row) {
  return { PASSED: 'success', FAILED: 'danger', NOT_EVALUATED: 'info' }[gateValue(row, 'qualityStatus')] || 'info'
}
function goldTagType(row) {
  return { APPROVED: 'success', PARTIAL: 'warning', PROVISIONAL: 'info', LEGACY: 'info' }[gateValue(row, 'goldStatus')] || 'info'
}
function gateLabel(row) {
  return { PUBLISHABLE: '可发布', BLOCKED: '不可发布' }[gateValue(row, 'publishStatus')] || '未计算'
}
function gateTagType(row) {
  return { PUBLISHABLE: 'success', BLOCKED: 'warning' }[gateValue(row, 'publishStatus')] || 'info'
}
function gateFilterValue(row) {
  const publishStatus = gateValue(row, 'publishStatus')
  if (publishStatus !== 'UNKNOWN') return publishStatus
  if (['QUEUED', 'PRECHECKING', 'RUNNING'].includes(row?.status)) return 'PENDING'
  return 'UNCOMPUTED'
}
function gateFilterLabel(value) {
  return {
    PUBLISHABLE: '可发布',
    BLOCKED: '不可发布',
    PENDING: '待评测',
    UNCOMPUTED: '未计算',
  }[value] || '未计算'
}
function hasRunComponent(row, component) {
  const features = parseFeatures(row?.featuresJson)
  const rerank = rerankExecution(row)
  return {
    MODEL: Boolean(features.model),
    PROMPT: Boolean(features.promptVersion),
    RERANK_REQUESTED: features.rerank !== false,
    RERANK_DISABLED: features.rerank === false,
    RERANK_MODEL: rerank.label === '模型重排序已执行',
    RERANK_FALLBACK: ['重排序降级为关键词', '混合重排序'].includes(rerank.label),
    TARGETED_RETRIEVAL: row?.runtimeEngine === 'langgraph'
      && Number(features.targetedRetrievalRetries || 0) > 0,
    COVERAGE_REFLECTION: row?.runtimeEngine === 'langgraph'
      && features.coverageReflection !== false,
  }[component] === true
}
function clearRunFilters() {
  runFilters.value = { runtime: [], component: [], status: [], gate: [] }
}
function gateIssueText(row) {
  const gate = releaseGate(row)
  if (!gate) return ''
  const failures = Array.isArray(gate.failures) ? gate.failures.map(item => item.message || item.metric).filter(Boolean) : []
  const blockers = Array.isArray(gate.blockingReasons) ? gate.blockingReasons : []
  return [...blockers.map(reason => `阻断：${reason}`), ...failures].join('；')
}
function formatDatasetType(v) {
  return {
    CONTRACT_REVIEW: '风险审查',
    RISK_REVIEW: '风险审查',
    CONTRACT_INTAKE: '首次合同识别',
    INTAKE: '合同要素提取',
    ELEMENT_EXTRACTION: '合同要素提取',
    CONTRACT_ELEMENT_EXTRACTION: '合同要素提取',
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
  if (['FAILED', 'ENVIRONMENT_UNAVAILABLE'].includes(row?.status)) {
    // 手动中止的部分评测：指标列可能为空，真实值在 summary_json.partialMetrics
    const summary = parseSummary(row?.summaryJson)
    const value = Number(row?.[key] ?? summary.partialMetrics?.[key])
    if (summary.partialMetrics && Number.isFinite(value)) return `${(value * 100).toFixed(0)}%（部分）`
    return '-'
  }
  const value = Number(row?.[key])
  return Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : '-'
}
function operations(row) {
  const summary = parseSummary(row?.summaryJson)
  return summary.operations || row?.operations || {}
}
function operationValue(row, key) {
  const value = operations(row)[key]
  return value === undefined || value === null || value === '' ? null : value
}
function formatLatency(value) {
  const milliseconds = Number(value)
  if (!Number.isFinite(milliseconds)) return '未观测'
  return `${(milliseconds / 1000).toFixed(1)} 秒`
}
function formatTokens(input, output) {
  if (input === null && output === null) return '未观测'
  return `入 ${Number(input || 0).toLocaleString()} / 出 ${Number(output || 0).toLocaleString()}`
}
function formatCost(value, currency) {
  if (value === null || value === undefined) return '不可用'
  return `${currency || 'USD'} ${Number(value).toFixed(6)}`
}
function formatExecutionStack(row) {
  const stack = operationValue(row, 'executionStack') || {}
  const model = (stack.model || []).join(', ')
  const graph = (stack.graphName || []).join(', ')
  const prompt = (stack.promptVersion || []).join(', ')
  return [graph, model, prompt].filter(Boolean).join(' · ') || '未观测'
}
function stopReason(row) {
  return parseSummary(row?.summaryJson).stopReason || ''
}
function rescoreInfo(row) {
  const summary = parseSummary(row?.summaryJson)
  const official = summary.officialHighRiskRecall
  if (official === undefined || official === null) return { official: null, tip: '' }
  const note = summary.rescore?.note || '评分器维度规范化修复后重算（未重跑用例，官方原值保留）'
  return {
    official,
    tip: `官方原值 ${(Number(official) * 100).toFixed(0)}% → 重算 ${note}`,
  }
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
  if (summary.partialMetrics) {
    const done = Number(summary.partialMetrics.metricCaseCount ?? row?.passedCount ?? 0)
    return `${done}/${total}（部分）`
  }
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
.actual-stage-section { margin: 0 0 14px; }
.actual-stage-section h5 { margin: 12px 0 8px; color: #475569; font-size: 13px; }
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

/* Run filters */
.run-filters {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin-bottom: 14px;
  padding: 12px 14px;
  background: #f8fafc;
  border: 1px solid #dce4ee;
  border-radius: 4px;
}
.run-filter-group {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-height: 26px;
}
.run-filter-label {
  flex: 0 0 auto;
  padding-top: 3px;
  color: #607184;
  font-size: 12px;
  font-weight: 800;
}
.run-filter-options {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
}
.run-filter-options .el-checkbox {
  height: 24px;
  margin-right: 0;
}
.run-filter-options .el-checkbox__label {
  padding-left: 5px;
  color: #4a5b6e;
  font-size: 12px;
}
.run-filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 26px;
  margin-left: auto;
}
.run-filter-count {
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
}

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
.muted { color: #a8abb2; }
.artifact-block { max-height: 420px; }
.gate-detail { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.gate-issues { color: #8a5b00; font-size: 12px; line-height: 1.5; }
.task-metric-list { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 10px; line-height: 1.5; font-size: 12px; color: #4a5b6e; }

/* Compare */
.version-board { margin-bottom: 24px; }
.version-board h4 { margin: 0 0 10px; color: #1f2d3d; font-size: 14px; }
.version-board .el-table { border: 1px solid #dce4ee; border-radius: 4px; }

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
