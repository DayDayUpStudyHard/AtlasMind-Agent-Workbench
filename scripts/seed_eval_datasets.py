#!/usr/bin/env python3
"""Seed comprehensive evaluation datasets directly via MySQL.

~150 cases covering 5 contract types × 7 scenarios × 8 difficulty levels × 10 risk dims.
Metadata: scenario, industry, difficulty, noiseLevel, mustHaveContractCitation, mustHavePolicyCitation.

DB credentials are read from environment variables (with defaults for local dev):
  EVAL_DB_HOST, EVAL_DB_PORT, EVAL_DB_USER, EVAL_DB_PASSWORD, EVAL_DB_NAME

Safety: set EVAL_SEED_CONFIRM=yes to actually run. Without it the script prints what it would
do and exits. Set EVAL_SEED_CLEAR=no to skip the DELETE step (append-only mode).

Usage:
  EVAL_SEED_CONFIRM=yes PYTHONIOENCODING=utf-8 python scripts/seed_eval_datasets.py
"""
import json, os, sys, pymysql

DB = {
    "host": os.getenv("EVAL_DB_HOST", "localhost"),
    "port": int(os.getenv("EVAL_DB_PORT", "3306")),
    "user": os.getenv("EVAL_DB_USER", "root"),
    "password": os.getenv("EVAL_DB_PASSWORD", ""),
    "database": os.getenv("EVAL_DB_NAME", "atlasmind_agent"),
    "charset": "utf8mb4",
}

DS = [
  {"name":"风险审查回归集","version":"v2","contract_type":"CONTRACT_REVIEW","desc":"付款/验收/责任上限/解除/知产/保密/争议解决全维度，7场景×8难度，重点补货物采购、工程、NDA、模糊验收、缺失责任上限、OCR噪声。"},
  {"name":"要素提取基准集","version":"v2","contract_type":"INTAKE","desc":"甲乙方/金额/币种/日期/生效条件等要素提取，覆盖金额歧义、日期歧义、OCR噪声、跨段落、附件信息。"},
  {"name":"履约日程提取集","version":"v2","contract_type":"FULFILLMENT_TIMELINE","desc":"交付里程碑/付款节点/验收期限/质保起算/续约窗口等日程提取，覆盖模糊节点、跨段落、歧义日期。"},
  {"name":"履约核验检查集","version":"v2","contract_type":"FULFILLMENT_CHECK","desc":"交付物验收/进度款条件/质保义务/违约责任触发/到期处理，覆盖缺失条款、冲突条款、OCR噪声。"},
  {"name":"综合压力测试集","version":"v2","contract_type":"COMPREHENSIVE","desc":"混合风险+要素+日程+核验的复杂合同，多种难度叠加：噪声+歧义+跨段落+附件。"},
]

def C(key,title,text,exp,nf,cite=0,sc="",ind="",diff="",noise="NONE",cc=0,pc=0):
  return (key,title,text.strip(),json.dumps(exp,ensure_ascii=False),json.dumps(nf,ensure_ascii=False),cite,sc,ind,diff,noise,cc,pc)

# ═══════════════════════════════════════════════════════════════════════
# 1. CONTRACT_REVIEW — 风险审查 (30 cases)
# ═══════════════════════════════════════════════════════════════════════
REVIEW = [
  # ── SERVICE_PROCUREMENT (4) ──
  C("CR-001","服务采购-付款条款单方有利(EASY)",
    """技术服务合同
甲方：上海明远科技有限公司
乙方：北京云图数据有限公司
第二条 付款方式
2.1 乙方完成全部开发工作并经甲方验收合格后，甲方在180个工作日内支付合同总价款的100%。
2.2 甲方有权根据自身资金安排单方面调整付款时间，乙方不得因此主张违约责任。
2.3 乙方不得以任何理由暂停或中止服务，否则视为根本违约，甲方有权解除合同并追究乙方全部损失。""",
    [{"title":"付款周期过长(180个工作日≈9个月)，乙方现金流风险极高","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"甲方单方面调整付款时间的权利无任何限制，构成显失公平","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"乙方不得暂停服务条款剥夺同时履行抗辩权(民法典第525条)","severity":"MEDIUM","riskDimension":"LIABILITY"}],
    ["付款方式为分期支付","甲方需支付预付款"],3,"SERVICE_PROCUREMENT","信息技术","EASY","NONE",1,1),

  C("CR-002","服务采购-验收标准由甲方单方决定(FUZZY)",
    """市场推广服务合同
甲方：北京美达化妆品有限公司
乙方：杭州蜂巢传媒有限公司
第四条 验收标准
4.1 推广效果以甲方内部评估为准，甲方有权根据市场变化调整验收指标。
4.2 若甲方认为推广效果未达预期，乙方应在10个工作日内免费补量投放。
4.3 推广"效果"包括但不限于品牌声量、用户心智、社交传播等综合维度。""",
    [{"title":"验收标准完全由甲方主观判断，无客观量化指标，乙方无法预判履约标准","severity":"HIGH","riskDimension":"ACCEPTANCE"},
     {"title":"'品牌声量/用户心智'等验收指标不可度量，构成验收标准虚置","severity":"HIGH","riskDimension":"ACCEPTANCE"},
     {"title":"补量投放无次数上限，乙方成本敞口不可控","severity":"MEDIUM","riskDimension":"LIABILITY"}],
    ["验收标准包含明确的KPI指标"],2,"SERVICE_PROCUREMENT","消费品","FUZZY","NONE",0,0),

  C("CR-003","服务采购-缺少责任上限条款(MISSING_CLAUSE)",
    """IT运维服务合同
甲方：招商银行股份有限公司
乙方：深圳鹏达信息技术有限公司
第一条 服务范围：7×24小时数据中心运维
第二条 服务费：RMB 12,000,000元/年
第三条 SLA：可用性不低于99.9%
(合同全文共12页，未约定赔偿责任上限)""",
    [{"title":"合同缺少赔偿责任上限条款——乙方对数据丢失/业务中断的赔偿风险无上限","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"银行核心系统运维无责任上限——单次事故潜在损失可能达数亿元","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["合同约定赔偿上限为年服务费的2倍"],1,"SERVICE_PROCUREMENT","金融","MISSING_CLAUSE","NONE",0,0),

  C("CR-004","服务采购-跨页面的隐藏终止约束(CROSS_PARAGRAPH)",
    """品牌战略咨询服务合同
甲方：比亚迪股份有限公司
乙方：麦肯锡(上海)咨询有限公司
第三条第3款(第5页)：本合同期限为三年，自生效日起算。
第七条第7.4款(第12页)：甲方有权在提前15日书面通知后终止本合同，仅需支付截至终止日的实际服务天数的费用。
第九条第9.2款(第18页)：如乙方在终止后2年内为甲方在新能源汽车领域的任何竞争者提供战略咨询服务，乙方应返还本合同项下已收取的全部服务费。
第十二条第12.1款(第22页)：合同终止后，乙方应在30日内向甲方移交全部工作成果，甲方无偿、永久、不可撤销地享有上述成果的全部知识产权。""",
    [{"title":"终止后2年竞业限制+返还全部服务费——惩罚性过强且无补偿","severity":"HIGH","riskDimension":"TERMINATION"},
     {"title":"终止后知识产权无偿归甲方——乙方的咨询方法论和工作成果被无偿剥夺","severity":"HIGH","riskDimension":"IP"},
     {"title":"终止通知期仅15天过短","severity":"MEDIUM","riskDimension":"TERMINATION"}],
    ["竞业限制有合理经济补偿"],2,"SERVICE_PROCUREMENT","汽车","CROSS_PARAGRAPH","NONE",1,0),

  # ── ENGINEERING_EPC (4) ──
  C("CR-005","工程合同-违约金明显过高(EASY)",
    """建设工程施工合同
发包人：绿地控股集团有限公司
承包人：中天建设集团有限公司
第十条 违约责任
10.1 承包人逾期竣工的，每逾期一日按合同总价款的0.5%支付违约金，累计不超过合同总价款的150%。
10.2 工程质量不合格的，发包人有权不支付任何剩余工程款，且承包人应赔偿发包人全部损失。
合同总价：RMB 280,000,000元。竣工日期：2026年6月30日。""",
    [{"title":"每日0.5%违约金(约140万元/天)+150%上限=4.2亿元，显著超出实际损失","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"质量不合格扣全部剩余款项+全额赔偿，可能构成双重惩罚","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["违约金为合同总价的20%"],2,"ENGINEERING_EPC","房地产","EASY","NONE",1,0),

  C("CR-006","工程合同-模糊验收标准(FUZZY)",
    """精装修工程合同
发包人：华润置地有限公司
承包人：金螳螂建筑装饰股份有限公司
第五条 验收标准
5.1 装修效果应符合"五星级酒店标准"。
5.2 材料应使用"同档次进口品牌"。
5.3 工程质量应达到"发包人满意"的程度。
5.4 验收由发包人组织，发包人有权拒绝接受任何其认为不符合上述标准的工程部分。""",
    [{"title":"'五星级酒店标准'不是法定技术标准，无法客观衡量","severity":"HIGH","riskDimension":"ACCEPTANCE"},
     {"title":"'同档次进口品牌'定义不明确，履约争议风险极高","severity":"MEDIUM","riskDimension":"ACCEPTANCE"},
     {"title":"'发包人满意'作为验收标准——完全主观，乙方无法预见和满足","severity":"HIGH","riskDimension":"ACCEPTANCE"}],
    ["验收标准参照GB50300/GB50210等国家标准执行"],2,"ENGINEERING_EPC","房地产","FUZZY","NONE",0,0),

  C("CR-007","工程合同-安全责任条款冲突(CONFLICTING)",
    """EPC总承包合同
业主：宁德时代新能源科技股份有限公司
总包方：中国寰球工程有限公司
第3.5条(第8页)：总包方对施工现场安全生产负总责，承担全部安全责任。
第12.3条(第35页)：业主提供的工艺包中涉及危险化学品工艺设计的，如因工艺设计缺陷导致安全事故，业主承担相应责任。
第18.1条(第50页)：无论何种原因导致的安全事故，总包方均应承担全部赔偿责任，业主不承担任何责任。
第25.2条(第67页)：因业主提供的技术资料错误导致的一切后果由业主承担。""",
    [{"title":"安全责任归属前后矛盾：第3.5条总包负总责 vs 第12.3条工艺缺陷业主承担 vs 第18.1条总包全部承担","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"第18.1条'无论何种原因'总包全部承担与第12.3/25.2条直接冲突，适用重大不确定性","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["安全责任条款清晰一致"],2,"ENGINEERING_EPC","新能源","CONFLICTING","NONE",1,0),

  C("CR-008","工程合同-不可抗力范围限缩(EASY)",
    """水利工程合同
发包人：长江水利委员会
承包人：中国水利水电第七工程局有限公司
第十四条 不可抗力
14.1 本合同项下不可抗力仅指7级以上地震和特大洪水(重现期≥100年)。
14.2 异常气象条件(包括暴雨、高温、寒潮)、地质灾害(滑坡、泥石流)、政府行为均不属于不可抗力。
14.3 承包人不得以不可抗力为由主张工期顺延或费用补偿。""",
    [{"title":"不可抗力范围被严重限缩——排除了常见的地质灾害和政府行为","severity":"HIGH","riskDimension":"FORCE_MAJEURE"},
     {"title":"即使发生不可抗力也不得主张工期顺延——违反民法典第590条","severity":"HIGH","riskDimension":"FORCE_MAJEURE"}],
    ["不可抗力包括地质灾害和异常气象"],2,"ENGINEERING_EPC","水利","EASY","NONE",1,1),

  # ── GOODS_PROCUREMENT (5) [URGENT] ──
  C("CR-009","货物采购-质保过短+质检条款陷阱(EASY)",
    """设备采购合同
买方：青岛海尔股份有限公司
卖方：某压缩机供应商
第六条 质量保证
6.1 设备质保期为交货后3个月。
6.2 买方应在收到货物后3个工作日内完成外观检查，逾期视为验收合格。
6.3 质保期满后卖方不再承担任何质量责任。""",
    [{"title":"3个月质保期对工业设备过短(行业通常12-24个月)","severity":"HIGH","riskDimension":"ACCEPTANCE"},
     {"title":"3个工作日外观检查期过短——无法完成实质性质量检验","severity":"MEDIUM","riskDimension":"ACCEPTANCE"},
     {"title":"质保期满后完全免责违反《产品质量法》关于缺陷产品责任的规定","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["质保期为24个月","质保期满后卖方仍承担缺陷产品责任"],2,"GOODS_PROCUREMENT","制造业","EASY","NONE",1,1),

  C("CR-010","货物采购-价格调整与终止缺失(MISSING_CLAUSE)",
    """原材料长期供应合同
买方：比亚迪汽车工业有限公司
供应商：某锂化合物生产企业
合同标的：电池级碳酸锂，每月500吨
合同期：3年(2025年7月1日至2028年6月30日)
价格条款(全文)：单价以每月首个工作日SMM电池级碳酸锂均价下浮5%为准。
(合同全文共5页，无终止条款、无价格异常波动处理机制、无争议解决条款)""",
    [{"title":"合同缺少终止条款——任何一方如何合法退出合同无约定","severity":"HIGH","riskDimension":"TERMINATION"},
     {"title":"合同缺少价格异常波动处理机制——锂价曾从5万飙升至60万/吨再回落，无上下限保护","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"合同缺少争议解决条款——发生纠纷时无管辖/仲裁约定","severity":"MEDIUM","riskDimension":"DISPUTE"}],
    ["合同第X条约定了终止程序"],2,"GOODS_PROCUREMENT","新能源","MISSING_CLAUSE","NONE",0,0),

  C("CR-011","货物采购-OCR扫描件金额识别干扰(OCR_NOISE)",
    """【OCR识别件—存在少量乱码】
设备采昀合同
买方：中建三局某团有限公司
卖方：三一重工股份有B公司
合同总价：RMB 18,600,OOO 元(大写：壹仟捌佰陆拾万元整)
注：上述总价中"OOO"为OCR将数字"000"误识别。
第三条 付款方式
3.1 预付款：合同总价的 3O%(即 RMB 5,58O,OOO 元)，合同签灯后 7 日内支付。
3.2 到货款：合同总价的 6O%，货物运抵现场并验收合格后 30 日内支付。
3.3 质保金：合同总价的 1O%，质保期满后 14 日内支付。""",
    [{"title":"合同总价金额OCR识别含'OOO'(实为'000')——18,600,000元","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"预付款比例'3O%'实为'30%'，OCR将'0'识别为'O'","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"甲方名称'中建三局某团有限公司'OCR识别错误(应为'集团有限公司')","severity":"LOW","riskDimension":"GENERAL"}],
    ["合同金额明确无歧义"],1,"GOODS_PROCUREMENT","建筑","OCR_NOISE","MEDIUM",0,0),

  C("CR-012","货物采购-前后规格冲突(CONFLICTING)",
    """精密仪器采购合同
买方：中国电子科技集团公司第十四研究所
卖方：是德科技(中国)有限公司
第1.2条(第2页)：采购信号分析仪N9040B型。
附件A技术规格书(第24页)：频率范围2Hz-50GHz，分析带宽510MHz。
第3.5条(第10页)：卖方保证所供仪器分析带宽不低于1GHz，以满足买方相控阵雷达测试需求。
(N9040B型出厂标准分析带宽为510MHz，1GHz需要N9041B型)""",
    [{"title":"分析带宽规格冲突：附件A标准510MHz vs 第3.5条约定1GHz——N9040B型无法满足","severity":"HIGH","riskDimension":"ACCEPTANCE"},
     {"title":"合同约定1GHz但指定型号不支持——需更换N9041B型(价差约USD 100,000+)","severity":"HIGH","riskDimension":"ACCEPTANCE"}],
    ["N9040B型满足合同全部要求"],2,"GOODS_PROCUREMENT","国防/电子","CONFLICTING","NONE",1,0),

  C("CR-013","货物采购-误报抑制:逾期违约金不违反法律(EASY)",
    """钢材采购合同
买方：中国中铁股份有限公司
卖方：宝山钢铁股份有限公司
第八条 违约责任
8.1 卖方逾期交货的，每逾期一日按逾期交付货物价值的0.05%支付违约金，累计不超过逾期货物价值的10%。
8.2 买方逾期付款的，每逾期一日按逾期支付金额的0.05%支付违约金，累计不超过逾期金额的10%。
8.3 因不可抗力导致逾期的不承担违约责任。
(注：本条为完全合法合理的违约金条款——双向对等、有上限、有不可抗力例外。不应报告任何风险。)""",
    [],
    ["违约金比例过高","违约金条款对买方不利","违约责任约定不明确","缺少不可抗力免责条款"],
    0,"GOODS_PROCUREMENT","钢铁","EASY","NONE",0,0),

  # ── SOFTWARE_IT (4) ──
  C("CR-014","软件合同-知识产权全盘转让无对价(EASY)",
    """委托开发合同
甲方：杭州极光人工智能研究院
乙方：独立开发者张伟
第五条 知识产权
5.1 乙方在履行本合同过程中产生的全部知识产权无偿、自动、不可撤销地全部转让给甲方。
5.2 乙方放弃与上述知识产权相关的一切人身权利，包括署名权。
5.3 合同终止后，乙方不得在任何形式的产品或服务中使用与本合同相关的任何技术方案。""",
    [{"title":"放弃署名权等著作人身权违反著作权法第10条强制性规定","severity":"HIGH","riskDimension":"IP"},
     {"title":"知识产权无偿转让无对价","severity":"HIGH","riskDimension":"IP"},
     {"title":"合同终止后竞业限制范围过大——'任何技术方案'涵盖乙方全部知识技能","severity":"MEDIUM","riskDimension":"IP"}],
    ["知识产权归属按贡献比例分配"],2,"SOFTWARE_IT","人工智能","EASY","NONE",1,1),

  C("CR-015","软件合同-验收无限循环(FUZZY)",
    """SaaS定制开发合同
甲方：中国平安保险(集团)股份有限公司
乙方：北京北森云计算股份有限公司
第六条 验收
6.1 乙方交付后，甲方在30个工作日内进行验收。
6.2 如验收不通过，乙方应在15个工作日内完成修改并重新提交验收。
6.3 上述流程可重复进行，直至甲方验收通过为止。
6.4 验收标准以甲方业务部门最终确认为准——具体标准见甲方内部验收规范(该规范未作为合同附件)。""",
    [{"title":"验收-修改循环无次数上限——乙方可能陷入无限返工","severity":"HIGH","riskDimension":"ACCEPTANCE"},
     {"title":"验收标准引用了未作为合同附件的内部规范——乙方签约时无法知晓验收标准","severity":"HIGH","riskDimension":"ACCEPTANCE"}],
    ["验收循环上限为3次"],2,"SOFTWARE_IT","金融","FUZZY","NONE",0,0),

  C("CR-016","软件合同-缺少数据安全条款(MISSING_CLAUSE)",
    """人力资源管理系统采购合同
甲方：某省级人民医院
乙方：某医疗IT软件公司
合同标的：医院HR管理系统(含全部医护人员个人信息、薪酬数据)
合同金额：RMB 3,600,000元
(合同全文共15页，包含功能需求、实施计划、培训、维保等，但没有任何数据安全、个人信息保护、数据泄露通知等条款)""",
    [{"title":"合同缺失数据安全条款——系统处理医护人员个人信息但无安全保护约定","severity":"HIGH","riskDimension":"DATA"},
     {"title":"违反《个人信息保护法》第51-56条——处理敏感个人信息应采取必要保护措施","severity":"HIGH","riskDimension":"COMPLIANCE"}],
    ["合同第X条约定了数据安全保护义务"],1,"SOFTWARE_IT","医疗","MISSING_CLAUSE","NONE",0,1),

  C("CR-017","软件合同-OCR噪声+金额歧义(OCR_NOISE+AMBIGUITY)",
    """【OCR识别件—中等噪声】
软件开发合 同
甲 方：深训市腾讯计算机系统有限公司(注："深训"为OCR将"深圳"误识)
乙 方：北京字节 跳动旗下 巨量引擎
合同金 额：RMB 5,6OO,OOO元(大写：伍佰陆拾万元整)
人天单 价：RMB 3,500元/人天
结算方 式：按季度结算，每季度结束后 lO 个工作日内支付。
(注："lO"中第一字符为小写字母l，实为数字10)""",
    [{"title":"甲方名称'深训市'为OCR将'深圳'误识","severity":"LOW","riskDimension":"GENERAL"},
     {"title":"结算周期'lO个工作日'中'l'为小写字母L实为数字'1'——即10个工作日","severity":"MEDIUM","riskDimension":"PAYMENT"}],
    ["合同金额和期限完全清晰"],1,"SOFTWARE_IT","互联网","OCR_NOISE","MEDIUM",0,0),

  # ── NDA (5) [URGENT] ──
  C("CR-018","保密协议-保密期限永久(EASY)",
    """保密协议
披露方：北京字节跳动科技有限公司
接收方：德勤华永会计师事务所
第四条 保密期限
4.1 接收方的保密义务自本协议签署之日起永久有效。
4.2 保密义务不因本协议的任何原因终止而消灭。
4.3 "保密信息"包括接收方在尽调中接触到的全部信息，无论是否已为公众所知悉。""",
    [{"title":"保密期限'永久有效'——超出保护商业秘密的合理期限","severity":"HIGH","riskDimension":"IP"},
     {"title":"保密信息范围包含已为公众所知的信息——违反商业秘密的法定构成要件","severity":"HIGH","riskDimension":"IP"},
     {"title":"未区分密级和保密措施","severity":"MEDIUM","riskDimension":"IP"}],
    ["保密信息仅限未公开的商业秘密","保密期限为合同终止后3年"],2,"NDA","互联网/专业服务","EASY","NONE",1,1),

  C("CR-019","NDA-保密信息定义过宽(FUZZY)",
    """员工保密与知识产权协议
雇主：上海邃原科技有限公司(AI芯片创业公司)
员工：芯片设计工程师 陈工
第一条 保密信息定义
1.1 "保密信息"指员工在公司任职期间以任何方式接触或知悉的全部信息，包括但不限于：
(a)技术信息：芯片架构、RTL代码、仿真结果、流片数据；
(b)商业信息：融资计划、客户名单、供应商信息；
(c)一般信息：公司内部邮件、会议记录、工作安排、食堂菜谱。
1.2 员工不确定某信息是否属于保密信息的，应默认其为保密信息。
1.3 员工离职后终身不得向任何第三方披露上述任何信息。""",
    [{"title":"'食堂菜谱/工作安排'等一般信息纳入保密范围——定义过宽","severity":"MEDIUM","riskDimension":"IP"},
     {"title":"'不确定则默认保密'——举证责任倒置，员工承担全部判断风险","severity":"HIGH","riskDimension":"IP"},
     {"title":"离职后终身保密——违反劳动合同法第23条竞业限制最长2年的规定","severity":"HIGH","riskDimension":"IP"}],
    ["保密信息定义合理且区分密级"],2,"NDA","半导体","FUZZY","NONE",1,1),

  C("CR-020","NDA-缺少保密信息销毁/返还条款(MISSING_CLAUSE)",
    """尽职调查保密协议
披露方：苏州康华生物科技有限公司(Pre-IPO)
接收方：中信证券股份有限公司(承销商)
目的：香港联交所IPO尽职调查
第二条 保密义务：接收方应对披露方提供的全部信息严格保密。
第七条 协议终止：本协议自IPO完成之日起终止。
(协议全文共6页，无任何关于尽调结束后保密信息的销毁/返还条款)""",
    [{"title":"协议缺少保密信息销毁/返还条款——协议终止后如何处理已获取的保密信息无约定","severity":"HIGH","riskDimension":"IP"},
     {"title":"IPO尽调涉及公司全部核心商业机密——缺乏销毁/返还机制带来永久泄露风险","severity":"HIGH","riskDimension":"IP"}],
    ["协议第X条约定了销毁/返还程序"],1,"NDA","生物医药","MISSING_CLAUSE","NONE",0,0),

  C("CR-021","NDA-误报抑制:合理使用限制不应报风险(AMBIGUITY)",
    """战略合作保密协议
甲方：华为技术有限公司
乙方：某芯片IP供应商
第三条 保密信息使用限制
3.1 接收方仅可为评估双方潜在战略合作之目的使用保密信息。
3.2 接收方不得将保密信息用于任何其他目的，包括但不限于自身产品开发、专利申请、反向工程等。
3.3 接收方可向为评估目的而确需知悉的关联公司员工披露保密信息。
第十条 甲方确认不承担保密信息准确性的保证义务，不对因使用保密信息产生的任何损失负责。
(注：3.3的"向关联公司员工披露"是合理的尽调需要，不是风险。3.2的"反向工程禁止"在芯片IP评估中是行业惯例。真正的风险是第10条。)""",
    [{"title":"甲方不保证保密信息准确性且概不负责——接收方基于不准确信息做出的商业决策风险全部自身承担","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"尽调中'不保证准确性'条款将尽调风险完全转嫁接收方","severity":"MEDIUM","riskDimension":"LIABILITY"}],
    ["向关联方披露保密信息属于泄露风险","禁止反向工程不合理","保密协议必须保证披露信息准确"],
    1,"NDA","半导体","AMBIGUITY","NONE",1,0),

  C("CR-022","NDA-违约金不合理+过度限制(EASY)",
    """员工竞业限制协议
雇主：某AI芯片公司
员工：算法工程师 李明
第四条 竞业限制
4.1 员工离职后2年内不得从事与AI芯片相关的任何工作。
4.2 竞业限制补偿金：每月RMB 2,000元(员工离职前月薪RMB 65,000元)。
4.3 员工违反竞业限制的，应支付违约金RMB 5,000,000元。""",
    [{"title":"竞业补偿金仅RMB 2,000/月(月薪的3%)——远低于法定标准的30%","severity":"HIGH","riskDimension":"IP"},
     {"title":"违约金RMB 5,000,000元与补偿金RMB 48,000元(24×2,000)严重不成比例","severity":"HIGH","riskDimension":"IP"},
     {"title":"'AI芯片相关任何工作'范围过宽——剥夺员工基本就业权","severity":"HIGH","riskDimension":"IP"}],
    ["竞业补偿金合理","违约金与补偿金比例合理"],2,"NDA","半导体","EASY","NONE",1,0),

  # ── OPS_MAINTENANCE (4) ──
  C("CR-023","运维合同-自动续约陷阱(EASY)",
    """SaaS服务订阅协议
甲方：成都好滋味餐饮管理有限公司
乙方：上海餐道信息科技有限公司
第六条 合同期限与续约
6.1 本合同有效期一年，自2025年3月1日至2026年2月28日。
6.2 合同到期前90日内，如甲方未书面通知乙方不再续约，则本合同自动续约一年，续约价格在原价格基础上上浮15%。
6.3 自动续约后，甲方不得在续约期内提前解约，否则需支付剩余服务期全部费用。""",
    [{"title":"自动续约价格年涨15%无上限——3年后费用增长52%","severity":"HIGH","riskDimension":"TERMINATION"},
     {"title":"提前90天通知实际仅给15天决定窗口","severity":"MEDIUM","riskDimension":"TERMINATION"},
     {"title":"续约期内不得解约+违约金为剩余全款——锁定效应过强","severity":"MEDIUM","riskDimension":"TERMINATION"}],
    ["合同到期自动终止"],2,"OPS_MAINTENANCE","餐饮","EASY","NONE",1,0),

  C("CR-024","物业合同-争议解决剥夺诉权(EASY)",
    """物业管理服务合同
业主：上海华贸中心物业管理有限公司
物业使用人：小红书科技有限公司
第十五条 争议解决
15.1 因本合同引起的争议提交业主所在地人民法院诉讼解决。
15.2 物业使用人放弃就本合同争议向任何仲裁机构申请仲裁的权利。
15.3 物业使用人承诺不就争议事项申请财产保全或证据保全。""",
    [{"title":"放弃财产保全和证据保全权利——严重削弱物业使用人救济能力","severity":"HIGH","riskDimension":"DISPUTE"},
     {"title":"放弃仲裁权利——剥夺争议解决选择权","severity":"MEDIUM","riskDimension":"DISPUTE"},
     {"title":"管辖指定业主所在地法院——增加物业使用人诉讼成本","severity":"MEDIUM","riskDimension":"DISPUTE"}],
    ["双方均可选择仲裁或诉讼"],2,"OPS_MAINTENANCE","商业地产","EASY","NONE",1,1),

  C("CR-025","物业合同-缺少解除权(MISSING_CLAUSE)",
    """商业综合体租赁合同
出租人：万达商业管理集团有限公司
承租人：海底捞国际控股有限公司
租赁面积：1,200㎡，租赁期限：8年(2025.12.1-2033.11.30)
月租金：RMB 280,000(前3年)，此后每2年递增8%
(合同全文28页，无任何承租人提前解除权或合同终止条款)""",
    [{"title":"合同完全缺少承租人提前解除权——8年长租期下无法合法退出","severity":"HIGH","riskDimension":"TERMINATION"},
     {"title":"经营不善需关店将面临8年全期租金索赔(潜在损失约RMB 2,688万+)","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["合同第X条约定了提前解约程序"],1,"OPS_MAINTENANCE","餐饮/商业地产","MISSING_CLAUSE","NONE",0,0),

  C("CR-026","维修合同-变更条款不明确(FUZZY)",
    """年度设备维修保养合同
甲方：中国石油化工股份有限公司
乙方：沈阳鼓风机集团服务有限公司
第七条 维修范围变更
7.1 甲方有权根据生产需要随时调整维修范围和内容。
7.2 因调整产生的费用由双方"合理协商"确定。
7.3 如双方无法就费用调整达成一致，乙方仍应先行执行甲方的变更指令，不得影响生产。""",
    [{"title":"甲方有权随时单方变更维修范围——无任何限制","severity":"HIGH","riskDimension":"CHANGE"},
     {"title":"'合理协商'无期限和机制——乙方可能无限期等待费用确认","severity":"MEDIUM","riskDimension":"CHANGE"},
     {"title":"协商不成仍需先行执行——乙方被迫接受甲方费用提案","severity":"HIGH","riskDimension":"CHANGE"}],
    ["变更需双方书面确认"],2,"OPS_MAINTENANCE","石化","FUZZY","NONE",0,0),

  # ── MIXED (4) ──
  C("CR-027","混合-跨境法律适用(EASY)",
    """跨境技术许可合同
许可方：Tesla Inc.(美国特拉华州)
被许可方：比亚迪股份有限公司
第十四条 适用法律与争议解决
14.1 本合同适用美国纽约州法律，排除CISG的适用。
14.2 合同语言为英文，中文翻译版本仅供参考，不具有法律效力。
14.3 争议提交美国纽约南区联邦地区法院管辖。""",
    [{"title":"适用纽约州法律排除中国法——中国境内合同受外国法律管辖风险极高","severity":"HIGH","riskDimension":"DISPUTE"},
     {"title":"纽约南区法院管辖导致被许可方诉讼成本极高","severity":"HIGH","riskDimension":"DISPUTE"},
     {"title":"中文版本无法律效力——被许可方在理解和履约上处于劣势","severity":"MEDIUM","riskDimension":"GENERAL"}],
    ["管辖地为中国贸仲委"],2,"MIXED","汽车/新能源","EASY","NONE",1,0),

  C("CR-028","混合-附件中的隐藏排他条款(ATTACHMENT_ONLY)",
    """年度广告投放框架合同
广告主：联合利华(中国)有限公司
代理方：上海蓝色光标公关顾问有限公司
合同正文(18页)约定了投放金额、媒体渠道、KPI、结算等，无任何排他性约定。
附件D《媒体资源保障承诺书》(第3页第2段)：
"代理方承诺在本合同有效期内，不代理任何与广告主在个人护理品类存在竞争关系的品牌的广告投放业务。如违反，退还已收全部服务费并赔偿RMB 50,000,000元。" """,
    [{"title":"排他条款仅出现在附件D中——正文无任何引用或提示，签约时极易被忽略","severity":"HIGH","riskDimension":"IP"},
     {"title":"违约金RMB 50,000,000+退还全部服务费——惩罚性极高","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"'个人护理品类竞争品牌'定义不明确——代理方难以判断合规边界","severity":"MEDIUM","riskDimension":"IP"}],
    ["合同无排他性限制"],2,"MIXED","消费品","ATTACHMENT_ONLY","NONE",1,0),

  C("CR-029","混合-金额歧义+期限识别错误(AMBIGUITY)",
    """联合营销合作协议
甲方：京东商城
乙方：某品牌方
第四条 营销费用
4.1 甲方投入营销费用不低于RMB 10O0万元(大写：壹仟万元整)。
(注："O"为OCR将"0"误识——实际1,000万元)
4.2 活动期间为2025年IO月1日至2026年3月31日。
(注："IO"中的"O"实为"0"——即10月1日)
4.3 乙方承担营销费用的50%(以甲方实际投入为基数)。
4.4 甲方实际投入以甲方内部财务口径为准。""",
    [{"title":"甲方实际投入以'甲方内部财务口径为准'——乙方无法独立核实结算基数","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"日期'IO月'中的'O'实为'0'——即10月","severity":"LOW","riskDimension":"GENERAL"}],
    ["甲方投入金额可由第三方审计核实"],1,"MIXED","电商","AMBIGUITY","MEDIUM",0,0),

  C("CR-030","混合-责任上限被附件覆盖(ATTACHMENT_ONLY)",
    """数据中心托管服务合同
客户：中国银联股份有限公司
服务商：万国数据服务有限公司
正文第十五条(第45页)："服务商累计赔偿总额不超过客户在导致索赔的事件发生前12个月内已支付的服务费总额。"
附件F《关键服务等级协议SLA》(第78页附录第3.2段)：
"对于因服务商重大过失或故意行为导致的数据永久丢失、业务中断超过4小时的，前条责任上限不适用，服务商应承担客户的全部实际损失。" """,
    [{"title":"责任上限条款正文和附件冲突——正文限上限，附件SLA重大过失突破上限","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"'重大过失'法律定义模糊——双方对触发条件理解可能不同","severity":"MEDIUM","riskDimension":"LIABILITY"}],
    ["责任上限条款在所有情形下均适用"],2,"MIXED","金融/数据中心","ATTACHMENT_ONLY","NONE",1,0),
]

# ═══════════════════════════════════════════════════════════════════════
# 2. INTAKE — 要素提取 (25 cases)
# ═══════════════════════════════════════════════════════════════════════
INTAKE = [
  C("IN-001","要素-标准服务合同(EASY)",
    """物业管理服务合同
甲方：深圳市万科物业服务有限公司
乙方：广州市绿城清洁服务有限公司
合同金额：人民币 3,600,000 元整
签订日期：2025年1月15日
合同期限：自2025年2月1日至2027年1月31日止，共24个月
付款方式：按月支付，每月15日前支付人民币150,000元""",
    [{"title":"甲方:深圳市万科物业服务有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"乙方:广州市绿城清洁服务有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"金额:3,600,000元/人民币","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"期限:2025-02-01至2027-01-31，24个月","severity":"LOW","riskDimension":"TERMINATION"}],
    [],5,"SERVICE_PROCUREMENT","物业管理","EASY","NONE",0,0),

  C("IN-002","要素-金额歧义(AMBIGUITY)",
    """年度审计服务合同
甲方：宁德时代新能源科技股份有限公司
乙方：普华永道中天会计师事务所
审计费：RMB 12,000,000元/年(含税)
差旅费：实报实销，预算不超过审计费的10%
(注："10%"——是审计费的10%=120万，还是合同总金额的10%？合同总金额是否含差旅费？)
合同期限：2025年度至2027年度审计""",
    [{"title":"甲方:宁德时代新能源科技股份有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"审计费:12,000,000元/年","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"差旅费上限:审计费的10%(1,200,000元)——基数歧义","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"期限:2025-2027(3年)","severity":"LOW","riskDimension":"TERMINATION"}],
    [],4,"SERVICE_PROCUREMENT","制造业/审计","AMBIGUITY","NONE",0,0),

  C("IN-003","要素-OCR噪声干扰(OCR_NOISE)",
    """【OCR扫描件—低噪声】
法 律顾 问聘 任合 同
甲 方：中国平安保 险(集团)股份有限 公司
乙 方：北京市金杜 律师 事务所
年 度顾问费：RMB 8,OOO,OOO 元(大写：捌佰万元整)
聘 任期 间：2O25年7月1日至2O27年6月3O日
(注：多处"O"为OCR将"0"误识别，"2O25"实为"2025")""",
    [{"title":"甲方:中国平安保险(集团)股份有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"乙方:北京市金杜律师事务所","severity":"LOW","riskDimension":"PARTY"},
     {"title":"年度顾问费:RMB 8,000,000元","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"聘任期:2025-07-01至2027-06-30","severity":"LOW","riskDimension":"TERMINATION"}],
    [],4,"SERVICE_PROCUREMENT","金融/法律","OCR_NOISE","LOW",0,0),

  C("IN-004","要素-跨段落信息分散(CROSS_PARAGRAPH)",
    """市场调研服务合同
(第1页)甲方：伊利实业集团股份有限公司
(第3页)调研范围：全国36个城市、108个样本点
(第5页)服务费总额：RMB 5,800,000元
(第8页)付款节点：签约后40%=2,320,000元，中期30%=1,740,000元，终期30%=1,740,000元
(第10页)本合同自2025年9月1日起生效
(第12页)乙方应在合同生效后18个月内完成全部调研工作
(甲乙方信息仅在第1页出现一次，合同期限分散在第10和12页)""",
    [{"title":"甲方:伊利实业集团股份有限公司(仅第1页)","severity":"LOW","riskDimension":"PARTY"},
     {"title":"服务费:RMB 5,800,000元(第5页)","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"生效:2025-09-01(第10页)，期限:18个月(第12页)","severity":"LOW","riskDimension":"TERMINATION"}],
    [],3,"SERVICE_PROCUREMENT","消费品","CROSS_PARAGRAPH","NONE",0,0),

  C("IN-005","要素-工程合同多金额(EASY)",
    """建设工程施工合同
发包人：上海陆家嘴金融贸易区开发股份有限公司
承包人：中国建筑第八工程局有限公司
签约合同价：RMB 2,800,000,000元(28亿元)
安全文明施工费：RMB 56,000,000元
暂列金额：RMB 140,000,000元
暂估价：RMB 280,000,000元
质量保证金：结算总价3%
开工日期：2025年4月1日，竣工日期：2028年3月31日，工期1095天""",
    [{"title":"发包人:上海陆家嘴金融贸易区开发股份有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"承包人:中国建筑第八工程局有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"签约价:28亿元(含暂列1.4亿+暂估2.8亿+安全0.56亿)","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"工期:2025-04-01至2028-03-31，1095天","severity":"LOW","riskDimension":"DATE"}],
    [],4,"ENGINEERING_EPC","房地产","EASY","NONE",0,0),

  C("IN-006","要素-附件中的联合体信息(ATTACHMENT_ONLY)",
    """EPC总承包合同
发包人：宁德时代新能源科技股份有限公司
承包人：中国寰球工程有限公司
签约价：EUR 7,350,000,000元(正文第2页)
工期：2025年11月1日至2028年10月31日(正文第3页)
(正文未列出承包人联合体成员)
附件A《联合体协议》：
联合体成员：牵头方-中国寰球工程有限公司(60%工程设计/采购/项目管理)；
成员方一-中建三局集团有限公司(25%土建施工)；
成员方二-西门子(中国)有限公司(15%自动化系统集成)""",
    [{"title":"发包人:宁德时代新能源科技股份有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"总价:EUR 7,350,000,000","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"联合体:寰球60%/中建三局25%/西门子15%(附件A)","severity":"LOW","riskDimension":"PARTY"}],
    [],3,"ENGINEERING_EPC","新能源","ATTACHMENT_ONLY","NONE",0,0),

  C("IN-007","要素-工程合同缺失关键工期信息(MISSING_CLAUSE)",
    """装修工程合同
发包人：某商业管理公司
承包人：某装饰公司
合同金额：RMB 4,500,000元
开工日期：2025年6月1日
(合同全文8页，无竣工日期、无工期约定、无中间验收节点)""",
    [{"title":"竣工日期:缺失","severity":"HIGH","riskDimension":"DATE"},
     {"title":"工期:缺失——无法判断是否逾期","severity":"HIGH","riskDimension":"DATE"},
     {"title":"中间验收节点:缺失","severity":"MEDIUM","riskDimension":"ACCEPTANCE"}],
    [],2,"ENGINEERING_EPC","商业装修","MISSING_CLAUSE","NONE",0,0),

  C("IN-008","要素-货物采购双币种(EASY)",
    """设备进口合同
买方：三一重工股份有限公司
卖方：Komatsu Ltd.
合同总价：USD 8,500,000(CIF上海港，INCOTERMS 2020)
预付定金：15%(USD 1,275,000)
签订日期：2025年03月10日
交货日期：2025年09月30日前
支付币种：美元(以付款当日央行中间价折算)
质保期：最终验收后18个月""",
    [{"title":"买方:三一重工股份有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"卖方:Komatsu Ltd.","severity":"LOW","riskDimension":"PARTY"},
     {"title":"总价:USD 8,500,000","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"币种:美元(USD)","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"签订:2025-03-10，交货:2025-09-30","severity":"LOW","riskDimension":"DATE"},
     {"title":"质保期:18个月","severity":"LOW","riskDimension":"ACCEPTANCE"}],
    [],6,"GOODS_PROCUREMENT","工程机械","EASY","NONE",0,0),

  C("IN-009","要素-货物采购缺甲方信息(MISSING_CLAUSE)",
    """印刷服务协议
甲方(委托方)：(空白)
乙方(承印方)：北京新华印刷有限公司
印刷数量：100,000册，单价RMB 12.5元/册，总价RMB 1,250,000元
交货日期：2025年6月15日
(甲方及盖章处均为空白)""",
    [{"title":"乙方:北京新华印刷有限公司","severity":"LOW","riskDimension":"PARTY"},
     {"title":"总价:RMB 1,250,000元","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"交货:2025-06-15","severity":"LOW","riskDimension":"DATE"},
     {"title":"甲方:缺失/空白——合同主体不完整，合同未成立或效力待定","severity":"HIGH","riskDimension":"PARTY"}],
    [],4,"GOODS_PROCUREMENT","印刷/出版","MISSING_CLAUSE","NONE",0,0),

  C("IN-010","要素-软件框架合同无总金额(EASY)",
    """IT外包服务框架协议
甲方：招商银行股份有限公司
乙方：中软国际科技服务有限公司
人员单价：高级工程师RMB 3,500/人天，中级RMB 2,200/人天，初级RMB 1,200/人天
框架期限：2025年1月1日至2027年12月31日
结算：按月据实结算。本框架不约定总金额。""",
    [{"title":"甲方:招商银行","severity":"LOW","riskDimension":"PARTY"},
     {"title":"乙方:中软国际","severity":"LOW","riskDimension":"PARTY"},
     {"title":"单价:高级3,500/中级2,200/初级1,200元/人天","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"期限:2025-01-01至2027-12-31","severity":"LOW","riskDimension":"TERMINATION"},
     {"title":"总金额:无(据实结算)","severity":"LOW","riskDimension":"PAYMENT"}],
    [],5,"SOFTWARE_IT","金融/IT","EASY","NONE",0,0),

  C("IN-011","要素-补充协议变更原合同(CROSS_PARAGRAPH)",
    """补充协议(二)
原合同：《云计算服务采购合同》(CT-2025-0032，签于2025年6月1日)
甲方：美团(北京)科技有限公司
乙方：北京优刻得云计算技术有限公司
1.原服务期"12个月"变更为"24个月"；
2.原月费"RMB 500,000元"变更为"RMB 450,000元"；
3.新增GPU集群服务月费RMB 200,000元。
变更后合同总金额由RMB 6,000,000元调整为RMB 15,600,000元。
本补充协议为原合同不可分割部分。签订日期：2025年9月1日""",
    [{"title":"甲方:美团","severity":"LOW","riskDimension":"PARTY"},
     {"title":"乙方:优刻得","severity":"LOW","riskDimension":"PARTY"},
     {"title":"变更后总金额:RMB 15,600,000元","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"变更后期限:24个月","severity":"LOW","riskDimension":"TERMINATION"},
     {"title":"新增GPU:200,000元/月","severity":"LOW","riskDimension":"PAYMENT"}],
    [],5,"SOFTWARE_IT","互联网","CROSS_PARAGRAPH","NONE",0,0),

  C("IN-012","要素-保密协议无金额(EASY)",
    """保密协议
披露方：北京字节跳动科技有限公司
接收方：德勤华永会计师事务所
签订日期：2025年2月10日
保密期限：自披露之日起5年
目的：财务审计及税务咨询
本协议不涉及任何费用支付。""",
    [{"title":"披露方:字节跳动","severity":"LOW","riskDimension":"PARTY"},
     {"title":"接收方:德勤","severity":"LOW","riskDimension":"PARTY"},
     {"title":"签订:2025-02-10，保密期限:5年","severity":"LOW","riskDimension":"IP"}],
    [],3,"NDA","互联网/专业服务","EASY","NONE",0,0),

  C("IN-013","要素-物业租赁多级递增(EASY)",
    """商业综合体租赁合同
出租人：万达商业管理集团有限公司
承租人：海底捞国际控股有限公司
租赁面积：1,200㎡，期限：8年(2025.12.1-2033.11.30)
月租金：RMB 280,000(前3年免递增，此后每2年递增8%)
装修免租期：90天，签订日期：2025年9月15日""",
    [{"title":"出租人:万达","severity":"LOW","riskDimension":"PARTY"},
     {"title":"承租人:海底捞","severity":"LOW","riskDimension":"PARTY"},
     {"title":"期限:2025-12-01至2033-11-30(8年)","severity":"LOW","riskDimension":"TERMINATION"},
     {"title":"递增:前3年免增，此后每2年8%","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"免租期:90天","severity":"LOW","riskDimension":"DATE"}],
    [],5,"OPS_MAINTENANCE","餐饮/商业地产","EASY","NONE",0,0),

  C("IN-014","要素-10%歧义(AMBIGUITY)",
    """设备租赁合同
出租方：上海宏信建设发展有限公司
承租方：中建三局集团有限公司
租赁物：塔式起重机TC7025×2台，月租金RMB 120,000元/台
保证金：合同总租金的10%
(合同未明确"合同总租金"计算方式——按最短租期6个月？预计租期18个月？)
最短租期：6个月，预计租期：18个月""",
    [{"title":"保证金基数'合同总租金'歧义：最短6月=1,440,000 vs 预计18月=4,320,000，保证金相差3倍","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"出租方:上海宏信","severity":"LOW","riskDimension":"PARTY"},
     {"title":"月租:120,000元/台×2=240,000元/月","severity":"LOW","riskDimension":"PAYMENT"}],
    [],3,"OPS_MAINTENANCE","建筑","AMBIGUITY","NONE",0,0),

  C("IN-015","要素-中外文混合合同(EASY)",
    """License and Distribution Agreement
许可方(Licensor)：Microsoft Corporation, a Washington corporation
被许可方(Licensee)：神州数码(中国)有限公司
Territory: PRC (excluding Hong Kong SAR, Macau SAR, and Taiwan)
License Fee: USD 45,000,000 per annum
Initial Term: 3 years from the Effective Date
Effective Date: July 1, 2025
Governing Language: English prevails over Chinese translation""",
    [{"title":"许可方:Microsoft Corporation","severity":"LOW","riskDimension":"PARTY"},
     {"title":"被许可方:神州数码","severity":"LOW","riskDimension":"PARTY"},
     {"title":"许可费:USD 45,000,000/年","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"期限:3年，自2025-07-01起","severity":"LOW","riskDimension":"TERMINATION"},
     {"title":"区域:中国大陆(不含港澳台)","severity":"LOW","riskDimension":"GENERAL"}],
    [],5,"MIXED","软件/IT分销","EASY","NONE",0,0),

  C("IN-016","要素-OCR高噪声+歧义叠加(OCR_NOISE+AMBIGUITY)",
    """【OCR扫描件—高噪声】
合 同
甲 方：深圳 市华 为技术 有限公 司
乙 方：中 国移动通 信集团 广东有 限公司
合 同金额：RMB l2,600,OOO 元
(注："l2"首字符为小写L，"OOO"为OCR将"000"误识)
签 订日 期：2O25 年lO 月 8 日
(注："O"实为"0"，"l"实为"1")
付 款方 式：签约后 l5 日内支付 3O% 预付款""",
    [{"title":"金额:RMB 12,600,000元(OCR修复后)","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"日期:2025-10-08(OCR修复后)","severity":"LOW","riskDimension":"DATE"},
     {"title":"预付款:30%，签约后15日内","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"甲方:深圳市华为技术有限公司(OCR修复后)","severity":"LOW","riskDimension":"PARTY"}],
    [],4,"MIXED","电信/IT","OCR_NOISE","HIGH",0,0),

  # ── Additional cases covering missing scenarios ──
  C("IN-017","要素-服务合同多方法律关系(EASY)",
    """联合体投标协议
牵头方：中铁大桥局集团有限公司(60%)
成员方一：中铁第四勘察设计院集团有限公司(25%)
成员方二：上海市政工程设计研究总院(15%)
投标项目：杭州湾跨海铁路大桥(设计施工总承包)
投标总价：RMB 18,500,000,000元
签订日期：2025年4月28日""",
    [{"title":"牵头方:中铁大桥局(60%)","severity":"LOW","riskDimension":"PARTY"},
     {"title":"成员一:铁四院(25%)","severity":"LOW","riskDimension":"PARTY"},
     {"title":"成员二:上海市政院(15%)","severity":"LOW","riskDimension":"PARTY"},
     {"title":"总价:185亿元","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"项目:杭州湾跨海铁路大桥","severity":"LOW","riskDimension":"GENERAL"}],
    [],5,"MIXED","基建","EASY","NONE",0,0),

  C("IN-018","要素-融资租赁特殊要素(EASY)",
    """融资租赁合同
出租人：工银金融租赁有限公司
承租人：中国国际航空股份有限公司
租赁物：A350-900飞机×1架(MSN 0583)
租赁本金：USD 320,000,000
租赁利率：3M SOFR+1.85%
租赁期限：12年(144个月)，自交付日起算
租金支付：等额本金，按季支付
购买选择权：期满时承租人有权以USD 1.00名义价购买
交付日期(预计)：2026年1月20日
签订日期：2025年6月12日""",
    [{"title":"出租人:工银租赁","severity":"LOW","riskDimension":"PARTY"},
     {"title":"承租人:国航","severity":"LOW","riskDimension":"PARTY"},
     {"title":"本金:USD 320,000,000，利率:3M SOFR+1.85%","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"期限:12年/144个月","severity":"LOW","riskDimension":"TERMINATION"},
     {"title":"购买选择权:USD 1.00名义价","severity":"LOW","riskDimension":"GENERAL"}],
    [],5,"MIXED","航空/金融","EASY","NONE",0,0),

  C("IN-019","要素-政府补助项目(EASY)",
    """科技计划项目合同
项目承担单位：清华大学
项目负责人：李明教授
项目编号：2025YFB0100200
资助金额：RMB 600万元(中央财政)
自筹经费：RMB 400万元
起止：2025年7月1日至2028年6月30日
拨款：2025年240万，2026年200万，2027年160万(绩效评估后拨付)""",
    [{"title":"承担单位:清华大学","severity":"LOW","riskDimension":"PARTY"},
     {"title":"资助:600万(财政)+400万(自筹)","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"起止:2025-07-01至2028-06-30(3年)","severity":"LOW","riskDimension":"TERMINATION"},
     {"title":"负责人:李明教授","severity":"LOW","riskDimension":"GENERAL"}],
    [],4,"MIXED","科研/教育","EASY","NONE",0,0),

  C("IN-020","要素-意向书/备忘录(EASY)",
    """战略合作备忘录
甲方：中国石油天然气集团有限公司
乙方：BP p.l.c.
双方达成初步合作意向：
1.拟在广东共同投资建设LNG接收站，预计总投资约USD 3,000,000,000；
2.股权比例拟为甲方51%、乙方49%；
3.本备忘录不构成具有法律约束力的协议，以正式合资合同为准。
签署日期：2025年4月15日""",
    [{"title":"甲方:中石油","severity":"LOW","riskDimension":"PARTY"},
     {"title":"乙方:BP","severity":"LOW","riskDimension":"PARTY"},
     {"title":"预计投资:USD 3,000,000,000","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"签署:2025-04-15","severity":"LOW","riskDimension":"DATE"},
     {"title":"法律效力:不具约束力","severity":"LOW","riskDimension":"GENERAL"}],
    [],5,"MIXED","能源","EASY","NONE",0,0),
]

# ═══════════════════════════════════════════════════════════════════════
# 3. FULFILLMENT_TIMELINE — 履约日程 (25 cases)
# ═══════════════════════════════════════════════════════════════════════
TIMELINE = [
  C("FT-001","日程-多里程碑付款节点(EASY)",
    """IT系统开发合同
甲方：比亚迪股份有限公司
乙方：用友网络科技股份有限公司
第五条 付款里程碑
5.1 蓝图确认后10个工作日内支付合同总价20%=RMB 1,000,000元
5.2 原型验收后10个工作日内支付25%=RMB 1,250,000元
5.3 UAT测试后10个工作日内支付35%=RMB 1,750,000元
5.4 稳定运行6个月终验后10个工作日内支付15%=RMB 750,000元
5.5 12个月质保期后10个工作日内支付尾款5%=RMB 250,000元
合同总价：RMB 5,000,000元。签订日期：2025年3月1日""",
    [{"title":"蓝图:20%,原型:25%,上线:35%,终验:15%,质保:5%","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"总价:RMB 5,000,000元","severity":"LOW","riskDimension":"PAYMENT"}],
    [],2,"SOFTWARE_IT","制造业/IT","EASY","NONE",0,0),

  C("FT-002","日程-分期交付验收(EASY)",
    """定制设备合同
买方：中国商飞上海飞机制造有限公司
卖方：德国杜尔系统股份有限公司
交付计划：
- 第一批(涂装机器人×4台)：2025.9.30前交付，45天验收
- 第二批(输送系统)：2025.12.31前交付，60天验收
- 第三批(烘干系统)：2026.3.31前交付，45天验收
- 整体联调：2026.6.30前完成
- 最终验收：联调后90天内性能考核
签订：2025年5月15日""",
    [{"title":"第一批:2025-09-30,45天验收","severity":"LOW","riskDimension":"DELIVERY"},
     {"title":"第二批:2025-12-31,60天验收","severity":"LOW","riskDimension":"DELIVERY"},
     {"title":"第三批:2026-03-31,45天验收","severity":"LOW","riskDimension":"DELIVERY"},
     {"title":"联调:2026-06-30,终验:联调后90天","severity":"LOW","riskDimension":"MILESTONE"}],
    [],4,"GOODS_PROCUREMENT","航空制造","EASY","NONE",0,0),

  C("FT-003","日程-续约窗口期(EASY)",
    """办公场所租赁合同
出租方：北京华贸中心物业管理有限公司
承租方：小红书科技有限公司
租赁期限：2025.10.1-2028.9.30(3年)
免租装修期：2025.10.1-2025.11.30(2个月，免租不免物业水电)
续租：期满前6个月(2028.4.1前)书面通知，租金上浮不超过8%
签订：2025年8月15日""",
    [{"title":"租赁:2025-10-01至2028-09-30(3年)","severity":"LOW","riskDimension":"TERMINATION"},
     {"title":"免租装修:2025-10-01至2025-11-30(2个月)","severity":"LOW","riskDimension":"DATE"},
     {"title":"续租通知截止:2028-04-01前(期满前6个月)","severity":"LOW","riskDimension":"TERMINATION"}],
    [],3,"OPS_MAINTENANCE","互联网/商业地产","EASY","NONE",0,0),

  C("FT-004","日程-进度百分比付款(EASY)",
    """工程设计合同
发包人：雄安新区规划建设局
设计人：中国建筑设计研究院有限公司
设计费支付：
- 签约后14天支付15%=RMB 4,500,000元(预付款)
- 方案通过规委会审查后14天支付至40%
- 初步设计通过专家评审后14天支付至65%
- 施工图通过审查后14天支付至90%
- 竣工验收通过后14天支付至100%
合同总价：RMB 30,000,000元。签于2025年2月20日""",
    [{"title":"预付款:15%(4,500,000元),签约后14天","severity":"LOW","riskDimension":"PAYMENT"},
     {"title":"方案:累计40%,初步:65%,施工图:90%,竣工:100%","severity":"LOW","riskDimension":"PAYMENT"}],
    [],2,"ENGINEERING_EPC","政府/基建","EASY","NONE",0,0),

  C("FT-005","日程-合同生效条件触发日期(EASY)",
    """并购协议
收购方：美的集团股份有限公司
被收购方股东：德国KUKA AG全体股东
交割先决条件：
(a)中国发改委境外投资备案
(b)德国联邦经济部无异议证明
(c)欧盟反垄断审查通过
(d)收购方完成不少于RMB 50亿的银团融资
条件满足后15个营业日内完成交割。
签约后180日内条件未满足，任何一方可终止。
签约：2025年6月15日""",
    [{"title":"交割条件:发改委+德国无异议+欧盟反垄断+RMB 50亿融资","severity":"LOW","riskDimension":"GENERAL"},
     {"title":"交割期限:条件满足后15营业日","severity":"LOW","riskDimension":"DATE"},
     {"title":"终止触发:签约后180日(2025-12-12前)","severity":"LOW","riskDimension":"TERMINATION"}],
    [],3,"MIXED","制造业/并购","EASY","NONE",0,0),

  C("FT-006","日程-模糊节点(FUZZY)",
    """SaaS平台采购合同
甲方：海底捞国际控股有限公司
乙方：广州云徙科技有限公司
第四条 试用期
4.1 试用期自系统部署完成并交付甲方试用之日起算，为期"一段合理时间"。
4.2 试用期结束后如甲方满意，本合同自动转为正式服务合同，正式服务期为3年。
第八条 系统部署
"乙方应在本合同签订后尽快完成系统部署。"
签订日期：2025年5月1日""",
    [{"title":"试用期'一段合理时间'——无明确天数，无法确定转正日期","severity":"HIGH","riskDimension":"TERMINATION"},
     {"title":"系统部署'尽快完成'——无截止日期，无法约束乙方","severity":"HIGH","riskDimension":"MILESTONE"}],
    ["试用期明确为60天","部署截止日期明确"],2,"SOFTWARE_IT","餐饮/IT","FUZZY","NONE",0,0),

  C("FT-007","日程-工期延误节点重排(MISSING_CLAUSE)",
    """精装修工程合同
发包人：融创中国控股有限公司
承包人：金螳螂建筑装饰股份有限公司
开工：2025年6月1日
竣工：2025年11月30日(总工期183天)
(合同未约定中间验收节点、未约定工期延误后如何调整后续节点、未约定赶工措施)
合同总价：RMB 25,000,000元。签于2025年5月10日""",
    [{"title":"缺少中间验收节点——无法分段监控进度","severity":"MEDIUM","riskDimension":"MILESTONE"},
     {"title":"缺少工期延误后的节点调整机制——延误后全部节点失效","severity":"HIGH","riskDimension":"MILESTONE"}],
    ["合同约定了水电/墙地/木作等验收节点"],2,"ENGINEERING_EPC","房地产","MISSING_CLAUSE","NONE",0,0),

  C("FT-008","日程-OCR噪声干扰日期(OCR_NOISE)",
    """【OCR扫描件—日期噪声】
设备采购及安装合同
买方：某水电站开发公司
卖方：东方电气集团有限公司
合同签灯日期：2O25年O8月l5日
(注："O"="0","l"="1"——实际2025年08月15日)
交货期：合同签灯后 l8O 日内
安装完工期：交货后 9O 日内
调试完成期：安装完工后 6O 日内
质保期：调试完成后 24 个月
合同总价：RMB 420,000,000元""",
    [{"title":"签约:2025-08-15(OCR修复)","severity":"LOW","riskDimension":"DATE"},
     {"title":"交货:签约后180天内(约2026-02-11前)","severity":"LOW","riskDimension":"DELIVERY"},
     {"title":"安装:交货后90天，调试:安装后60天","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"质保:调试后24个月","severity":"LOW","riskDimension":"ACCEPTANCE"}],
    [],4,"GOODS_PROCUREMENT","能源/电力","OCR_NOISE","MEDIUM",0,0),

  C("FT-009","日程-跨段落节点分散(CROSS_PARAGRAPH)",
    """智慧园区建设项目
甲方：苏州工业园区管理委员会
乙方：华为+中国电信苏州分公司(联合体)
(第2页)Phase 1(基础设施)：2025.9.1-2025.12.31，5G基站、光纤、数据中心
(第5页)Phase 2(平台搭建)：2026.1.1-2026.4.30，IoT平台、数据中台、视频AI
(第9页)Phase 3(应用上线)：2026.5.1-2026.8.31，智能安防、停车、能耗管理
(第12页)Phase 4(试运行)：2026.9.1-2026.11.30(3个月)
(第15页)Phase 5(移交)：2026.12.31。每阶段验收通过方可进入下一阶段。""",
    [{"title":"P1:2025-09-01至12-31(5G/光纤/数据中心)(第2页)","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"P2:2026-01-01至04-30(IoT/数据中台)(第5页)","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"P3:2026-05-01至08-31(应用)(第9页)","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"门禁:每阶段验收通过方可进入下一阶段","severity":"LOW","riskDimension":"ACCEPTANCE"}],
    [],4,"MIXED","智慧城市","CROSS_PARAGRAPH","NONE",0,0),

  C("FT-010","日程-按月滚动(EASY)",
    """内容营销月度服务合同
甲方：伊利实业集团股份有限公司
乙方：上海蓝色光标公关顾问有限公司
服务内容(每月)：
- 每月25日前提交下月内容日历
- 每月产出原创文章≥20篇、短视频≥10条
- 每月30日前提交当月数据复盘报告
合同期限：2025.8.1-2026.7.31，月费：RMB 350,000元/月，每月5日前支付""",
    [{"title":"日历:每月25日前,产出:20篇+10条/月,复盘:每月30日前","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"付款:每月5日前,期限:2025-08-01至2026-07-31","severity":"LOW","riskDimension":"PAYMENT"}],
    [],2,"SERVICE_PROCUREMENT","消费品","EASY","NONE",0,0),

  C("FT-011","日程-返工重检时间窗口(EASY)",
    """OEM代工质量协议
委托方：苹果贸易(上海)有限公司
代工方：立讯精密工业股份有限公司
返工与重检：
- 出货检验不合格批次，3个工作日内完成返工并申请重检
- 委托方收到申请后2个工作日内安排重检
- 同一批次返工不超过2次，超过2次全批报废，费用代工方承担
- 报废产品10个工作日内完成补产并重检""",
    [{"title":"返工:3工作日,重检安排:2工作日,返工上限:2次","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"报废补产:10工作日","severity":"LOW","riskDimension":"MILESTONE"}],
    [],2,"GOODS_PROCUREMENT","电子制造","EASY","NONE",0,0),

  C("FT-012","日程-培训计划节点(EASY)",
    """SAP实施与培训合同
甲方：宁德时代新能源科技股份有限公司
乙方：SAP中国有限公司
上线日期目标：2026年1月4日
培训计划：
- 关键用户培训：上线前8周开始，为期2周
- 最终用户培训：上线前4周开始，分3批每批1周
- 管理员培训：上线前2周开始，为期1周
- 上线后跟踪辅导：上线后持续4周""",
    [{"title":"关键用户:上线前8周(约2025-11-09),2周","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"最终用户:上线前4周(约2025-12-07),3批","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"管理员:上线前2周(约2025-12-21)","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"上线:2026-01-04,辅导:上线后4周","severity":"LOW","riskDimension":"MILESTONE"}],
    [],4,"SOFTWARE_IT","新能源","EASY","NONE",0,0),

  C("FT-013","日程-附条件生效的变更(CROSS_PARAGRAPH)",
    """设备采购合同变更
买方：中国石化工程建设有限公司
卖方：沈阳鼓风机集团股份有限公司
(原合同CT-2025-0188)
2025年7月10日买方变更通知：压缩机SAC-4→SAC-6，加价RMB 5,200,000元
7月15日卖方回复：同意变更，交期延长60天——买方未书面回复
(卖方按变更后型号生产但交期延长了60天——买方主张逾期)""",
    [{"title":"变更函:2025-07-10(加价520万)","severity":"LOW","riskDimension":"CHANGE"},
     {"title":"卖方同意附带条件:交期延长60天(7月15日)","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"买方沉默是否构成默示同意——存在争议","severity":"HIGH","riskDimension":"GENERAL"}],
    [],2,"GOODS_PROCUREMENT","石化","CROSS_PARAGRAPH","NONE",0,0),

  C("FT-014","日程-展会紧耦合时间线(EASY)",
    """展览展示服务合同
主办方：中国国际进口博览局
搭建方：上海东浩兰生国际服务贸易(集团)有限公司
- 进场搭建：2025.10.28-11.2(6天)
- 展品布置：2025.11.3(1天)
- 展会期间：2025.11.5-11.10(6天)
- 撤展：2025.11.11-11.12(2天)
- 恢复场地：2025.11.13 18:00前
逾期恢复场地承担全额赔偿责任含候场损失。签于2025年8月1日""",
    [{"title":"搭建:10.28-11.2,布置:11.3,展会:11.5-11.10","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"撤展:11.11-11.12,恢复截止:11.13 18:00","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"逾期恢复:全额赔偿含候场损失","severity":"MEDIUM","riskDimension":"LIABILITY"}],
    [],3,"SERVICE_PROCUREMENT","会展","EASY","NONE",0,0),

  C("FT-015","日程-保证金释放条件(EASY)",
    """PPP项目合同
实施机构：武汉市城乡建设局
社会资本方：光大环境(集团)有限公司
建设期履约保证金：RMB 30,000,000元(开工前缴)
释放：竣工验收后30工作日释放50%，决算审计后30工作日释放剩余50%
运营期履约保证金：RMB 15,000,000元(运营开始前缴)
释放：运营期满+资产移交后30工作日全额释放
建设期：2025.12.1-2028.11.30，运营期：15年""",
    [{"title":"建设期保证金30M:开工前缴,竣工50%,决算50%","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"运营期保证金15M:运营前缴,期满+移交后释放","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"建设期:2025-12-01至2028-11-30","severity":"LOW","riskDimension":"DATE"}],
    [],3,"ENGINEERING_EPC","市政/环保","EASY","NONE",0,0),

  C("FT-016","日程-股权解禁(EASY)",
    """限制性股票授予协议
授予方：腾讯控股有限公司
被授予方：高级副总裁刘成
授予：100,000股，授予日2025年6月30日
解禁：
- 第一批30%：授予日满12个月(2026.6.30)
- 第二批30%：满24个月(2027.6.30)
- 第三批40%：满36个月(2028.6.30)
条件：解禁日在职且绩效≥B级
加速：控制权变更时全部立即解禁""",
    [{"title":"授予:2025-06-30(100,000股)","severity":"LOW","riskDimension":"DATE"},
     {"title":"解禁:30%@2026-06-30,30%@2027-06-30,40%@2028-06-30","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"条件:在职+绩效≥B,加速:控制权变更","severity":"LOW","riskDimension":"GENERAL"}],
    [],3,"MIXED","互联网/金融","EASY","NONE",0,0),

  C("FT-017","日程-供应商VMI补货节奏(EASY)",
    """供应商管理库存协议(VMI)
买方：比亚迪汽车工业有限公司
供应商：宁德时代新能源科技股份有限公司
库存水位：保持不低于5天、不高于10天生产用量
补货触发：库存<5天时24h内确认订单，48h内送达
月度对账：每月5日前
季度议价：每季度末协商调整价格
有效期：2025.7.1-2026.6.30""",
    [{"title":"库存水位:5-10天,确认:24h,送达:48h","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"对账:每月5日,议价:季度末","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"有效期:2025-07-01至2026-06-30","severity":"LOW","riskDimension":"TERMINATION"}],
    [],3,"GOODS_PROCUREMENT","新能源/汽车","EASY","NONE",0,0),

  C("FT-018","日程-物流合同变更通知期限(EASY)",
    """物流运输年度合同
托运方：京东物流集团
承运方：顺丰速运有限公司
合同变更通知期：至少45天书面通知
终止通知期：至少90天书面通知
旺季保护：11.1-1.31及6.1-6.30不得变更/终止
续约协商窗口：到期前60天(至2026.3.1前启动)
有效期：2025.5.1-2026.4.30""",
    [{"title":"变更:45天,终止:90天,旺季禁期:11-1月+6月","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"续约:到期前60天,有效期:2025-05-01至2026-04-30","severity":"LOW","riskDimension":"TERMINATION"}],
    [],2,"SERVICE_PROCUREMENT","物流","EASY","NONE",0,0),

  C("FT-019","日程-知识产权申请节点(EASY)",
    """技术合作研发合同
甲方：大疆创新科技有限公司
乙方：香港科技大学
项目启动：2025年7月1日
原型研发：2025.9.1-12.31(4个月)，交付可运行原型
专利申请：原型结束前至少3件PCT提交
论文发表：2026.6.30前至少1篇SCI一区
项目结题：2026.7.31，提交结题报告和源代码""",
    [{"title":"原型:2025-09-01至12-31","severity":"LOW","riskDimension":"MILESTONE"},
     {"title":"PCT:原型结束前≥3件,论文:2026-06-30前≥1篇SCI","severity":"LOW","riskDimension":"IP"},
     {"title":"结题:2026-07-31","severity":"LOW","riskDimension":"MILESTONE"}],
    [],3,"MIXED","科技/学术","EASY","NONE",0,0),

  C("FT-020","日程-框架下分批订单节点(EASY)",
    """年度IT设备采购框架
甲方：中信证券股份有限公司
乙方：联想(北京)信息技术有限公司
订单确认：乙方收到采购订单后5工作日内书面确认交期
替代方案：不能确认时3工作日内提出替代方案
常规订单：确认后30自然日内交付
加急订单：确认后10自然日内交付(加急费5%)
框架期限：2025.9.1-2027.8.31""",
    [{"title":"常规:确认后30天,加急:10天(+5%),确认:5工作日","severity":"LOW","riskDimension":"DELIVERY"},
     {"title":"替代:3工作日,框架:2025-09-01至2027-08-31","severity":"LOW","riskDimension":"TERMINATION"}],
    [],2,"GOODS_PROCUREMENT","金融/IT","EASY","NONE",0,0),
]

# ═══════════════════════════════════════════════════════════════════════
# 4. FULFILLMENT_CHECK — 履约核验 (25 cases)
# ═══════════════════════════════════════════════════════════════════════
CHECK = [
  C("FC-001","核验-交付物与约定不符(EASY)",
    """软件开发合同验收
甲方：华润置地有限公司
乙方：明源云科技有限公司
约定交付物：(a)ERP源代码及编译说明(b)系统架构设计文档(c)数据库ER图及数据字典(d)用户操作手册(e)运维手册(f)全部测试用例及报告
实际交付：源代码、操作手册、测试报告（缺少架构设计文档、ER图、运维手册）""",
    [{"title":"缺少系统架构设计文档","severity":"HIGH","riskDimension":"DELIVERY"},
     {"title":"缺少数据库ER图及数据字典","severity":"MEDIUM","riskDimension":"DELIVERY"},
     {"title":"缺少系统运维手册","severity":"MEDIUM","riskDimension":"DELIVERY"},
     {"title":"可主张修理/减价/赔偿(民法典第781条)","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["源代码存在质量问题"],4,"SOFTWARE_IT","房地产/IT","EASY","NONE",1,1),

  C("FC-002","核验-进度款支付条件未成就(EASY)",
    """工程施工进度款
发包人：绿地控股集团有限公司
承包人：中天建设集团有限公司
进度款流程：承包人每月25日提交工程量报告→监理7天核实→发包人确认后14天支付至80%
实际情况：2025年8月承包人报告声称完成产值RMB 120,000,000元，监理核实后确认为RMB 78,000,000元。""",
    [{"title":"承包人虚报工程量(声称120M vs 监理确认78M)","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"应付款:78,000,000×80%=62,400,000元(非96,000,000元)","severity":"MEDIUM","riskDimension":"PAYMENT"}],
    ["发包人逾期支付"],2,"ENGINEERING_EPC","房地产","EASY","NONE",1,0),

  C("FC-003","核验-质保期内缺陷响应(EASY)",
    """设备采购质保
买方：青岛海尔股份有限公司
卖方：西门子(中国)有限公司
质保：最终验收后24个月
响应：24h远程诊断→48h到场→7天修复/替换
超7天未修复：每天0.1%设备单价违约金
实际：2026.3.10故障当天通知。卖方3.12远程(超1天),3.15到场(超2天),3.25修复(超5天)。
设备单价RMB 850,000元。""",
    [{"title":"远程超1天,到场超2天,修复超5天(应7天内即3.20前)","severity":"HIGH","riskDimension":"SERVICE"},
     {"title":"违约金:5天×850,000×0.1%=4,250元","severity":"LOW","riskDimension":"LIABILITY"}],
    ["卖方响应完全合规"],2,"GOODS_PROCUREMENT","制造业","EASY","NONE",1,0),

  C("FC-004","核验-合同到期后继续履约(MISSING_CLAUSE)",
    """年度运维合同到期
甲方：中国银联股份有限公司
乙方：神州数码系统集成服务有限公司
合同期限：2024.7.1-2025.6.30。交接期不超过30天。
实际：合同2025.6.30到期未续约。乙方7-8月仍有运维人员驻场并出具服务费账单RMB 1,600,000元。甲方拒付。""",
    [{"title":"合同到期后服务费RMB 1,600,000元是否构成事实合同关系——核心争议","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"交接期应已在2025.7.30前完成","severity":"MEDIUM","riskDimension":"SERVICE"}],
    ["合同到期后权利义务自动终止"],2,"SERVICE_PROCUREMENT","金融/IT","MISSING_CLAUSE","NONE",0,0),

  C("FC-005","核验-解除后结算争议(CONFLICTING)",
    """合同解除结算
甲方：万科企业股份有限公司
乙方：南通三建集团有限公司
工程总价：RMB 580,000,000元。因甲方资金问题2025.10.15发出解除通知。
至此产值约RMB 320,000,000元。
甲方：已完工程按70%结算(RMB 224,000,000元)
乙方：按100%结算+窝工损失+已购材料+遣散费RMB 85,000,000元
合同约定："甲方有权因自身原因解除合同，但应赔偿乙方全部实际损失" """,
    [{"title":"结算比例争议:甲方70% vs 乙方100%——合同未约定解除后单价折扣","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"窝工/材料/遣散费RMB 85,000,000元属实际损失应有赔偿(合同明确)","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["合同解除后乙方无权索赔"],2,"ENGINEERING_EPC","房地产","CONFLICTING","NONE",1,0),

  C("FC-006","核验-履约保证金退还争议(EASY)",
    """工程履约保证金
业主：龙湖地产有限公司
总包：中国建筑第五工程局有限公司
保证金：RMB 20,000,000元
退还条件：竣工验收合格+竣工备案完成后30工作日
验收合格：2025.8.20，备案完成：2025.10.15
30工作日届满：2025.11.26
实际：截至2025.12.10业主未退还，理由是"景观绿化部分苗木需补种"——但竣工验收合格证已发。""",
    [{"title":"保证金未按期退还(截止2025-11-26已逾期14天)","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"绿化补种为质保义务非保证金退还前置条件——业主混同两项义务构成违约","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["绿化补种完成后方可退还保证金"],2,"ENGINEERING_EPC","房地产","EASY","NONE",1,0),

  C("FC-007","核验-不可抗力下履约争议(FUZZY)",
    """买卖合同
卖方：武汉华工激光工程有限责任公司
买方：深圳市大族激光科技股份有限公司
标的：激光切割机10台×RMB 1,200,000元，交付：2025.9.30前
事件：2025.9.20武汉5.3级地震(中国地震局测定)，卖方工厂受损→9.22通知不可抗力→10.15恢复生产→预计11.15交付
买方主张逾期违约金(每日0.1%)。卖方以不可抗力免责。""",
    [{"title":"地震构成不可抗力——9.20-10.15期间迟延可免责(25天)","severity":"MEDIUM","riskDimension":"FORCE_MAJEURE"},
     {"title":"10.15恢复后至11.15交付(约31天)不可抗力已消除——应承担违约责任","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["卖方完全不承担任何违约责任"],2,"GOODS_PROCUREMENT","制造业","FUZZY","NONE",1,0),

  C("FC-008","核验-背对背条款(EASY)",
    """专业分包Pay-when-paid
总包方：中国交通建设股份有限公司
分包方：江苏沪宁钢构股份有限公司
付款条件：总包方从业主收到对应工程款后方向分包方支付(pay-when-paid)
实际：分包工程2025.6.30完工验收。因总包与业主在总价上存在争议，业主至今(2025.12)未付。分包方多次催款被拒。""",
    [{"title":"Pay-when-paid条款效力存疑——总包怠于向业主主张则分包收款权无限悬空","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"如分包方为中小企业，《保障中小企业款项支付条例》第9条可挑战该条款效力","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"完工验收6个月未付款——可能构成实质性不公平","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["Pay-when-paid条款绝对有效"],3,"ENGINEERING_EPC","基建","EASY","NONE",1,1),

  C("FC-009","核验-违约金与定金竞合(EASY)",
    """预制品采购合同
买方：中建三局集团有限公司
卖方：杭萧钢构股份有限公司
定金：RMB 8,000,000元，总价：RMB 80,000,000元
违约金：逾期每天0.5%(即400,000元/天)
实际：卖方逾期60天。买方主张：(1)定金双倍返还RMB 16,000,000+(2)违约金24,000,000=RMB 40,000,000元。
民法典第588条：违约金与定金择一适用。""",
    [{"title":"违约金与定金不得并用(民法典588条)——择一适用","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"应择一:违约金24,000,000>定金罚则16,000,000，选违约金更有利","severity":"MEDIUM","riskDimension":"LIABILITY"},
     {"title":"买方40,000,000元索赔超出法定范围","severity":"HIGH","riskDimension":"LIABILITY"}],
    ["违约金与定金可同时主张"],3,"GOODS_PROCUREMENT","建筑","EASY","NONE",1,1),

  C("FC-010","核验-模糊验收标准(FUZZY)",
    """ERP系统实施验收
甲方：三一重工股份有限公司
乙方：用友网络科技股份有限公司
验收标准："系统上线后，由甲方各部门负责人在验收单上签字确认。如任何部门认为系统'不符合实际业务需要'，则该模块不予验收通过。"
(合同未定义"符合实际业务需要"的客观标准)""",
    [{"title":"验收标准纯主观——'不符合实际业务需要'无客观度量，甲方可无限次拒绝验收","severity":"HIGH","riskDimension":"ACCEPTANCE"},
     {"title":"任何单一部门均可否决——验收权碎片化，乙方无法控制","severity":"HIGH","riskDimension":"ACCEPTANCE"}],
    ["验收标准有明确的功能清单和测试用例"],2,"SOFTWARE_IT","制造业","FUZZY","NONE",0,0),

  C("FC-011","核验-知识产权许可超用(EASY)",
    """软件许可合规
被许可方：中国平安保险(集团)股份有限公司
许可方：甲骨文(中国)软件系统有限公司
许可：Oracle Database EE，100 Processor License，年费USD 5,000,000
审计发现：
- 生产环境：80 Processor(合规)
- 灾备环境：40 Processor(合同授权，合规)
- 测试环境：20 Processor(合同仅授权10 Processor，超量10)
- 开发环境：15 Processor(合同未授权！)
超量按标准许可费150%补缴。""",
    [{"title":"测试环境超量10 Processor——按150%补缴","severity":"HIGH","riskDimension":"IP"},
     {"title":"开发环境15 Processor完全未授权使用——构成侵权(计算机软件保护条例第24条)","severity":"HIGH","riskDimension":"IP"}],
    ["全部使用合规"],2,"SOFTWARE_IT","金融","EASY","NONE",1,1),

  C("FC-012","核验-变更指令超出合同范围(CONFLICTING)",
    """工程变更争议
发包人：华润万象生活有限公司
承包人：金螳螂精装科技(苏州)有限公司
原合同：商场公共区域精装修RMB 45,000,000元
变更#015：瓷砖→大理石+RMB 12,000,000
变更#023：LED大屏钢结构电气+RMB 8,000,000
变更#031：屋顶花园景观+RMB 15,000,000
累计变更：RMB 35,000,000元(占原合同77.8%)
承包人主张#023和#031超出原合同范围应另签合同。""",
    [{"title":"累计变更77.8%可能构成实质性变更(超出合理范围)","severity":"HIGH","riskDimension":"CHANGE"},
     {"title":"LED大屏+屋顶花园(RMB 23,000,000)超出原施工范围应另签","severity":"HIGH","riskDimension":"CHANGE"}],
    ["变更指令全部有效承包人必须执行"],2,"ENGINEERING_EPC","商业地产","CONFLICTING","NONE",1,0),

  C("FC-013","核验-破产情形下的合同处理(EASY)",
    """供应商破产
买方：格力电器股份有限公司
卖方：某压缩机零部件供应商(2025.11.1申请破产重整，11.10法院受理)
状况：
- 已收预付款RMB 15,000,000元，未交货物值约RMB 8,000,000元
- 买方仓库寄售存货值RMB 5,000,000元(合同约定所有权在买方使用时转移)
- 已交付未检验货值RMB 2,000,000元
合同第7条："一方进入破产程序的，另一方有权立即终止合同。" """,
    [{"title":"预付款15M:未供货部分约8M需申报破产债权(回收率可能极低)","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"寄售库存5M:所有权未转移属卖方破产财产","severity":"HIGH","riskDimension":"PROPERTY"},
     {"title":"已交未验货物:管理人有权选择继续履行或解除","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"合同终止条款受《企业破产法》第18条管理人选择权限制","severity":"HIGH","riskDimension":"TERMINATION"}],
    ["合同自动终止买方可直接取回寄售库存"],4,"GOODS_PROCUREMENT","制造业","EASY","NONE",1,1),

  C("FC-014","核验-ESG合规履约(FUZZY)",
    """绿色供应链条款
买方：苹果采购运营管理(上海)有限公司
供应商：某连接器生产企业
承诺：100%可再生能源电力，2030年前全价值链碳中和
违约：货值20%违约金+可立即终止合同
审计发现：2025年度可再生能源仅45%(承诺100%)。年货值约USD 200,000,000元。""",
    [{"title":"可再生能源45% vs 承诺100%——严重违约，约USD 40M违约金","severity":"HIGH","riskDimension":"COMPLIANCE"},
     {"title":"绿证市场供应不足是否构成不可抗力——合同未约定此场景","severity":"MEDIUM","riskDimension":"FORCE_MAJEURE"}],
    ["绿证不足属不可抗力可免责"],2,"GOODS_PROCUREMENT","电子制造","FUZZY","NONE",1,0),

  C("FC-015","核验-OCR噪声干扰履约记录(OCR_NOISE)",
    """【OCR扫描件—履约报告】
项 目月 度报 告(2025年 lO 月)
项目名 称：某地 铁线 路信号系 统
承 包商：中国 通号 上海 工程局
本 月完成 产值：RMB l2,5OO,OOO 元
(注："l"="1"，"OOO"="000"——12,500,000元)
累 计完成 产值：RMB 89,6OO,OOO 元(注：89,600,000元)
合 同总 价：RMB l56,OOO,OOO 元(注：156,000,000元)
累 计完 成比 例：57.44%
(合同约定按月支付至累计完成产值的85%，本月应付RMB lO,625,OOO元——注：10,625,000元)""",
    [{"title":"累计完成89,600,000/156,000,000=57.44%,应付10,625,000元","severity":"LOW","riskDimension":"PAYMENT"}],
    [],1,"ENGINEERING_EPC","轨道交通","OCR_NOISE","MEDIUM",0,0),

  C("FC-016","核验-安全责任事故(EASY)",
    """工程安全事故
施工合同
发包人：上海市政工程建设处
承包人：上海隧道工程股份有限公司
安全协议：承包人承担全部安全责任，确保零死亡。
事故：2025.9.15盾构段坍塌，2死3重伤，直接损失RMB 85,000,000元。
调查认定：(1)未按专项方案支护 (2)监测异常未及时停工撤人 (3)安全交底流于形式。
《安全生产法》第114条：重大事故处100万-500万罚款。""",
    [{"title":"事故:2死3重伤+85M损失=较大/重大事故","severity":"HIGH","riskDimension":"COMPLIANCE"},
     {"title":"行政处罚:100-500万罚款+暂扣安全生产许可证","severity":"HIGH","riskDimension":"COMPLIANCE"},
     {"title":"刑事责任:重大责任事故罪(刑法134条)","severity":"HIGH","riskDimension":"COMPLIANCE"}],
    ["承包人不承担安全责任"],3,"ENGINEERING_EPC","市政","EASY","NONE",1,1),

  C("FC-017","核验-多层级分包付款链断裂(EASY)",
    """工程分包付款链
总包：中国中铁股份有限公司→专业分包：上海建工集团→劳务分包：安徽众诚建筑劳务
付款链：业主→总包(60天)→专业分包(总包收款后30天)→劳务分包(收款后15天)
实际：业主6月款8.5支付→总包9.20付专业分包(逾期16天)→专业分包10.10付劳务(逾期10天)""",
    [{"title":"总包逾期16天:应收款后30天内(9/5前)实际9/20","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"专业分包逾期10天:应收款后15天内(10/5前)实际10/10","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"付款链传递延迟→《保障中小企业款项支付条例》风险","severity":"HIGH","riskDimension":"COMPLIANCE"}],
    ["劳务分包应自行垫付工资"],3,"ENGINEERING_EPC","基建","EASY","NONE",1,0),

  C("FC-018","核验-联合体连带责任(EASY)",
    """联合体工程
发包人：成都天府国际机场建设指挥部
联合体：北京城建(牵头)+中铁建设(成员)
事故：成员方钢结构焊缝探伤合格率仅85%(合同要求≥98%)，大面积返修费RMB 120,000,000元+延误90天。
成员方资金紧张无力承担。发包人要求牵头方承担连带责任。
《建筑法》第27条：共同承包各方承担连带责任。""",
    [{"title":"联合体对外连带(建筑法27条)——牵头方须垫付120M返修费","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"牵头方垫付后可向成员方追偿","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"焊缝85% vs 98%——严重质量违约","severity":"HIGH","riskDimension":"ACCEPTANCE"}],
    ["牵头方不承担成员方质量责任"],3,"ENGINEERING_EPC","基建/机场","EASY","NONE",1,1),

  C("FC-019","核验-误报抑制:完全合规的履约(EASY)",
    """IT运维服务季度报告
甲方：中国工商银行股份有限公司
乙方：神州数码系统集成服务有限公司
2025年Q3运维指标：
- 系统可用性：99.97%(合同要求99.9% ✓)
- 故障响应时间：平均8分钟(合同要求<15分钟 ✓)
- 故障修复时间：平均45分钟(合同要求<2小时 ✓)
- 备份成功率：100%(合同要求99.99% ✓)
- 安全事件：0起(合同要求0 ✓)
Q3服务费RMB 3,000,000元确认支付。
(注：本条所有指标均达标的正常履约——不应报任何风险)""",
    [],
    ["故障响应时间过长","系统可用性未达标","安全事件处理不当","备份成功率不足"],
    0,"SERVICE_PROCUREMENT","金融/IT","EASY","NONE",0,0),

  C("FC-020","核验-跨境支付汇率风险(EASY)",
    """外汇结算争议
买方：中国广核集团有限公司
卖方：Framatome SAS(法国)
合同金额：EUR 85,000,000
签约：2025.1.10(EUR/CNY=7.80)
发货：2025.7.8(EUR/CNY=8.35)
验收：2026.4.15(EUR/CNY=8.15)
合同无汇率锁定条款。三次购汇实际人民币成本比签约预算增加RMB 32,000,000元。""",
    [{"title":"无汇率锁定条款——买方承担全部汇率波动(损失约RMB 3,200万)","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"跨境大额合同缺乏汇率风险分担或远期锁汇机制","severity":"HIGH","riskDimension":"PAYMENT"}],
    ["卖方应承担汇率损失"],2,"GOODS_PROCUREMENT","核能/能源","EASY","NONE",0,0),
]

# ═══════════════════════════════════════════════════════════════════════
# 5. COMPREHENSIVE — 综合评测 (25 cases)
# ═══════════════════════════════════════════════════════════════════════
COMPREHENSIVE = [
  C("CP-001","综合-智慧工厂多风险+要素+节点(EASY)",
    """智慧工厂整体解决方案合同
甲方：宝山钢铁股份有限公司
乙方：西门子(中国)+上海宝信软件(联合体)
总价：RMB 680,000,000元。签于2025年3月15日
范围：MES/WMS/EMS/SCADA全流程智能制造
周期：Phase 1(2025.6.1-12.31)→P2(2026.1.1-6.30)→试运行(2026.10.1-12.31)
知识产权：全部软件著作权归甲方，乙方放弃署名权
违约责任：逾期每日0.3%违约金，甲方可直接抵扣，乙方不得以未收款为由停止工作
争议解决：甲方所在地法院管辖，乙方放弃上诉权""",
    [{"title":"知识产权全归甲方+放弃署名权:对乙方显失公平","severity":"HIGH","riskDimension":"IP"},
     {"title":"甲方可直接抵扣且乙方不得停工作:剥夺同时履行抗辩权","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"放弃上诉权无效:上诉权是法定程序权利","severity":"HIGH","riskDimension":"DISPUTE"},
     {"title":"甲方:宝钢","severity":"LOW","riskDimension":"PARTY"},
     {"title":"总价:RMB 680,000,000元","severity":"LOW","riskDimension":"AMOUNT"},
     {"title":"P1:2025-06-01至12-31","severity":"LOW","riskDimension":"MILESTONE"}],
    ["本合同条款均公平合理"],6,"MIXED","钢铁/智能制造","EASY","NONE",1,0),

  C("CP-002","综合-SaaS服务+数据+安全(EASY)",
    """人力资源SaaS云服务合同
甲方：中国平安保险(集团)股份有限公司
乙方：北京北森云计算股份有限公司
金额：RMB 24,000,000元/年(100,000用户)
期限：2025.7.1-2028.6.30
数据安全：乙方对全部数据安全承担全部责任，数据泄露按RMB 50,000元/用户赔偿(潜在RMB 50亿元)
SLA：可用性≥99.99%(年宕机≤52.56分钟)，未达标按100倍延长服务期""",
    [{"title":"数据安全全部责任由乙方承担(含非乙方过错的第三方攻击)","severity":"HIGH","riskDimension":"DATA"},
     {"title":"赔偿额RMB 50亿元可能超出乙方赔偿能力","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"99.99%可用性+100倍延长严厉","severity":"MEDIUM","riskDimension":"SERVICE"},
     {"title":"乙方:北森","severity":"LOW","riskDimension":"PARTY"},
     {"title":"期限:2025-07-01至2028-06-30","severity":"LOW","riskDimension":"TERMINATION"}],
    ["赔偿上限为年服务费"],5,"SOFTWARE_IT","金融/IT","EASY","NONE",1,0),

  C("CP-003","综合-跨国M&A(EASY)",
    """股权购买协议(SPA)
卖方：ABC Capital(开曼)
买方：国家集成电路产业投资基金三期
目标：美国硅谷AI芯片设计公司
对价：USD 850,000,000。签于2025年8月20日
交割条件：CFIUS审查+中国发改委/商务部ODI备案
分手费：CFIUS未批则买方支付USD 50,000,000反向分手费
管辖：美国特拉华州法律，HKIAC香港仲裁(英文)
卖方保证赔偿上限：USD 8,500,000(交易对价1%)""",
    [{"title":"卖方保证赔偿上限仅US$8.5M(1%):对US$850M交易过低","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"反向分手费USD 50M:买方单方承担CFIUS风险","severity":"MEDIUM","riskDimension":"LIABILITY"},
     {"title":"特拉华州法律+香港仲裁:买方争议成本高","severity":"MEDIUM","riskDimension":"DISPUTE"},
     {"title":"对价:USD 850M","severity":"LOW","riskDimension":"AMOUNT"}],
    ["赔偿上限合理"],4,"MIXED","半导体/投资","EASY","NONE",1,0),

  C("CP-004","综合-融资租赁+保险+税务(EASY)",
    """飞机融资租赁
出租人：工银金融租赁有限公司
承租人：春秋航空股份有限公司
机型：A321neo×5架，每架租期12年
租金：每季USD 1,100,000(3M SOFR+2.2%浮动)
交付：2026 Q2:2架,Q3:2架,Q4:1架
保险：机身/战争/第三者险，第一受益人为出租人
税务：增值税6%承租人承担""",
    [{"title":"利率风险:3M SOFR浮动+2.2%，加息周期成本增加","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"保险第一受益人出租人:承租人投保但赔付归出租人——不对等","severity":"MEDIUM","riskDimension":"GENERAL"},
     {"title":"承租人:春秋航空","severity":"LOW","riskDimension":"PARTY"},
     {"title":"交付:2026Q2(2架)Q3(2架)Q4(1架)","severity":"LOW","riskDimension":"MILESTONE"}],
    ["利率固定"],4,"MIXED","航空/金融","EASY","NONE",0,0),

  C("CP-005","综合-代工+排他+不竞争(EASY)",
    """OEM排他协议
品牌方：安踏体育用品有限公司
代工方：申洲国际集团控股有限公司
排他：代工方不得为任何竞品(含李宁/特步/耐克/阿迪中国业务)代工
期限：5年(2025.6.1-2030.5.31)，年最低500万件×RMB 85元/件
不竞争：合同终止后3年内，代工方不得为体育用品行业任何企业代工""",
    [{"title":"排他范围涵盖所有体育用品行业——超出保护品牌方合法商业利益所需","severity":"HIGH","riskDimension":"NON_COMPETE"},
     {"title":"终止后3年竞业无补偿——法院可认定无效","severity":"HIGH","riskDimension":"NON_COMPETE"},
     {"title":"5年固定单价85元无调价——对品牌方有利","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"品牌方:安踏","severity":"LOW","riskDimension":"PARTY"}],
    ["排他条款合理","竞业限制有补偿"],4,"MIXED","纺织/体育","EASY","NONE",1,0),

  C("CP-006","综合-租赁+装修+消防+物业(EASY)",
    """商业综合体租赁
出租人：万达商业管理集团有限公司
承租人：海底捞国际控股有限公司
面积：1,200㎡，期限：8年(2025.12.1-2033.11.30)
递增：前3年免增，此后每2年+8%
装修免租：90天
排他：出租人不得引入其他火锅类餐饮
消防：承租人自行办理二次消防验收——未通过损失自负，不免租金
退租：恢复租赁场地至毛坯状态""",
    [{"title":"消防风险由承租人单方承担:未通过不免租金","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"退租恢复毛坯:8年期重餐饮装修成本极高","severity":"HIGH","riskDimension":"TERMINATION"},
     {"title":"递增8%/2年:8年总涨约32%","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"免租装修:90天(2025.12.1-2026.2.28)","severity":"LOW","riskDimension":"MILESTONE"}],
    ["消防验收由出租人负责"],4,"OPS_MAINTENANCE","餐饮/商业地产","EASY","NONE",0,0),

  C("CP-007","综合-版权授权+分成+审计(FUZZY)",
    """影视版权许可
版权方：华策影视股份有限公司
平台方：北京爱奇艺科技有限公司
授权内容：某电视剧(45集)独家信息网络传播权
期限：5年(2025.9.1-2030.8.31)
授权费：基础RMB 180,000,000+会员播放RMB 0.05元/次+广告净收入30%+衍生品净收入15%
最低保障：每年≥RMB 12,000,000元
审计权：版权方每半年审计一次(差异>5%由平台方承担费用)""",
    [{"title":"播放量定义:'会员有效播放量'不够精确(P&G多少秒计有效？)","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"广告净收入未明确定义扣除项","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"版权方:华策","severity":"LOW","riskDimension":"PARTY"},
     {"title":"授权费:RMB 180,000,000+分成","severity":"LOW","riskDimension":"PAYMENT"}],
    ["分成定义完全清晰"],4,"MIXED","影视/互联网","FUZZY","NONE",0,0),

  C("CP-008","综合-PPP+土地+融资(EASY)",
    """污水处理厂PPP
政府方：东莞市生态环境局
社会资本方：北控水务集团有限公司
方式：BOT(建设3年+运营22年=25年)
总投资：RMB 1,200,000,000元
污水处理单价：RMB 1.85元/吨(前5年锁定，此后每3年按CPI调整)
保底水量：第1-3年60%，第4年起80%
提前终止补偿：因政府违约按未摊销投资+预期利润80%补偿""",
    [{"title":"预期利润计算方式未定义——执行争议风险","severity":"MEDIUM","riskDimension":"TERMINATION"},
     {"title":"保底水量第4年起80%需核实财政承受力","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"特许期:25年,单价:RMB 1.85/吨(前5年锁定)","severity":"LOW","riskDimension":"AMOUNT"}],
    ["协议条款均合理"],3,"MIXED","市政/环保","EASY","NONE",0,0),

  C("CP-009","综合-API服务+SLA+限流+数据(EASY)",
    """API技术服务
甲方：美团(北京三快在线科技有限公司)
乙方：高德软件有限公司
标的：地图API(展示/路径规划/POI搜索)
调用量：15亿次/年，服务费RMB 0.005元/次(超出0.008元/次)
SLA：99.95%(未达标100倍调用补偿)
限流：每应用QPS 5,000(超限不计SLA)
数据：脱敏出行数据(轨迹/POI热度)归乙方
免责：第三方云服务商故障不计SLA；API结果正确性和安全性乙方概不负责""",
    [{"title":"脱敏出行数据归乙方:轨迹和POI热度对美团有极高商业价值","severity":"HIGH","riskDimension":"DATA"},
     {"title":"API结果正确性和安全性免责极端(路径规划错误致事故仍可能侵权)","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"第三方故障不计SLA——乙方将基础设施风险转嫁甲方","severity":"MEDIUM","riskDimension":"SERVICE"},
     {"title":"甲方:美团","severity":"LOW","riskDimension":"PARTY"}],
    ["API结果免责条款合理","数据归属条款公平"],4,"SOFTWARE_IT","互联网","EASY","NONE",1,0),

  C("CP-010","综合-临床试验+伦理+赔偿(EASY)",
    """临床试验合同
申办方：江苏恒瑞医药股份有限公司
研究机构：北京大学第三医院
试验：III期，抗肿瘤生物制剂HR-2025-003
周期：2025.10.1-2027.9.30，500例
费用：RMB 85,000,000元
损害补偿：药物不良反应申办方全担；机构过失机构担；因果关系不明各50%
数据发表：数据归申办方，发表需申办方书面同意""",
    [{"title":"赔偿上限RMB 85,000,000:对500例肿瘤患者可能不足","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"数据归申办方+发表需同意:影响学术独立性","severity":"MEDIUM","riskDimension":"IP"},
     {"title":"因果关系不明各50%:应倾向于申办方承担","severity":"MEDIUM","riskDimension":"LIABILITY"}],
    ["研究机构可自由发表","申办方赔偿无上限"],3,"MIXED","医药/科研","EASY","NONE",0,0),

  C("CP-011","综合-跨境物流+仓储+报关(CROSS_PARAGRAPH)",
    """综合物流服务
甲方：Shein(广州希音供应链管理有限公司)
乙方：中国外运股份有限公司
服务：跨境出口物流全链条
期限：2025.11.1-2027.10.31
时效(第4页)：海运≤25天，空运≤7天，海外仓当天16:00前出库——未达标运费减免30%
报关(第7页)：乙方负责出口报关和进口清关(合同未约定海关罚款/扣货责任)
货损赔偿(第10页)：按申报价值60%，每票不超过USD 500""",
    [{"title":"报关责任不完整:海关罚款/扣货场景无责任约定——重大风险敞口","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"货损赔偿上限USD 500/票:对高价值服饰极不合理","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"甲方:Shein","severity":"LOW","riskDimension":"PARTY"}],
    ["报关风险由乙方全担"],3,"MIXED","电商/跨境物流","CROSS_PARAGRAPH","NONE",0,0),

  C("CP-012","综合-联合研发+专利池+开源(EASY)",
    """联合研发协议
甲方：百度网讯科技有限公司
乙方：清华大学智能产业研究院
领域：大语言模型推理优化
知识产权：共有专利各50%，甲方免费实施无需乙方同意，乙方向第三方许可须甲方同意。源码Apache 2.0开源，乙方贡献者须签CLA将版权授予甲方。
论文：第一作者乙方，通讯作者甲方，投稿前须经甲方合规审查。""",
    [{"title":"共有专利甲方免费实施但乙方许可须同意:权利不对等","severity":"HIGH","riskDimension":"IP"},
     {"title":"开源版权通过CLA归甲方:乙方学术贡献无法保留完整权利","severity":"MEDIUM","riskDimension":"IP"},
     {"title":"论文需甲方合规审查:可能影响学术发表自由","severity":"MEDIUM","riskDimension":"IP"}],
    ["知识产权归属完全公平"],3,"MIXED","AI/学术","EASY","NONE",1,0),

  C("CP-013","综合-矿产采购+质检+价格公式(EASY)",
    """铜精矿长期采购
买方：江西铜业股份有限公司
卖方：Glencore International AG
合同量：100,000干公吨/年
期限：2026.1.1-2028.12.31
作价公式：最终价格=(LME铜均价×铜含量%×回收率96.5%)-TC/RC
TC：USD 65/dmt，RC：USD 0.065/lb
铜含量<20%买方有权拒收
质检：以卸货港CIQ为最终依据(差异>±2%复检)
不可抗力：矿山停产/铁路中断/港口封锁致卖方无法供货，卖方免责且不承担买方替代采购价差""",
    [{"title":"不可抗力排除买方替代采购价差损失:卖方单方免责但买方损失巨大","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"买方:江铜","severity":"LOW","riskDimension":"PARTY"},
     {"title":"量:100,000dmt/年,期:2026-2028","severity":"LOW","riskDimension":"TERMINATION"}],
    ["不可抗力条款对双方公平"],3,"GOODS_PROCUREMENT","矿产/大宗","EASY","NONE",0,0),

  C("CP-014","综合-艺人经纪+肖像权+解约(EASY)",
    """艺人独家经纪合同
经纪公司：乐华娱乐(天津)文化传播有限公司
艺人：张某某
期限：7年(2025.10.1-2032.9.30)
收入分配：演艺30/70，广告40/60，自媒体20/80
肖像权：合约期间及终止后5年内独占性授予经纪公司
解约：艺人单方解约需支付剩余期限预计收入50%+宣传费×3+RMB 50,000,000元""",
    [{"title":"终止后5年独占肖像使用:侵犯人格权——违反民法典第1023条","severity":"HIGH","riskDimension":"IP"},
     {"title":"解约金累积极端严厉——剥夺艺人就业权","severity":"HIGH","riskDimension":"TERMINATION"},
     {"title":"7年期限对娱乐业过长","severity":"MEDIUM","riskDimension":"TERMINATION"}],
    ["解约条款合理","肖像权条款合法"],3,"MIXED","娱乐","EASY","NONE",1,0),

  C("CP-015","综合-能源合同+绿证+碳配额(EASY)",
    """PPA购电协议
购电方：特斯拉(上海)有限公司
售电方：大唐新能源股份有限公司
项目：200MW集中式光伏(内蒙古鄂尔多斯)
期限：20年(2026.1.1-2045.12.31)
电价：RMB 0.27/kWh(固定含税)
绿证：全部GEC归购电方
碳排放权：CEA归购电方，售电方不得另行申报CCER""",
    [{"title":"CEA归购电方独占:售电方失去CCER收入机会","severity":"HIGH","riskDimension":"GENERAL"},
     {"title":"20年固定电价无通胀调整——售电方长期收益不确定","severity":"MEDIUM","riskDimension":"PAYMENT"},
     {"title":"购电方:特斯拉","severity":"LOW","riskDimension":"PARTY"}],
    ["绿证和碳配额归属公平"],3,"MIXED","新能源","EASY","NONE",0,0),

  C("CP-016","综合-股权激励+业绩+离职(EASY)",
    """限制性股票授予
授予方：深圳市汇顶科技股份有限公司(A股)
被授予方：研发副总裁赵志强
授予：500,000股，行权价RMB 45.50元
生效：分4年等额(每年25%)，首年2026.7.1
业绩：公司2026-2029年度ROE≥15%且营收CAGR≥20%
离职处理：正常退休保留已生效期权；自愿离职全部立即作废(含已生效未行权)；过错解雇全部作废+已行权收益返还；死亡/伤残全部立即生效""",
    [{"title":"自愿离职已生效期权立即作废:对员工极为不利","severity":"HIGH","riskDimension":"TERMINATION"},
     {"title":"过错解雇已行权收益返还:法律效力存疑","severity":"MEDIUM","riskDimension":"LIABILITY"},
     {"title":"业绩ROE≥15%+CAGR≥20%双门槛极高——可能构成实质性不授予","severity":"MEDIUM","riskDimension":"GENERAL"}],
    ["离职处理条款公平","业绩条件合理"],3,"MIXED","半导体/金融","EASY","NONE",0,0),

  C("CP-017","综合-广告程序化+反作弊+数据(EASY)",
    """DSP广告合同
广告主：联合利华(中国)有限公司
DSP平台：北京品友互动信息技术有限公司
金额：RMB 50,000,000元
反作弊：GIVT过滤率≥99%，SIVT过滤后不收费
数据所有权：全部投放数据归广告主，DSP不得留存或用于优化
品牌安全：不得出现在成人/暴力/假新闻/版权侵权内容，每违规一次赔RMB 1,000,000元""",
    [{"title":"品牌安全每次RMB 1,000,000无累计上限——程序化亿次展示潜在赔偿额巨大","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"全部数据归广告主独占:DSP无法用数据优化模型","severity":"MEDIUM","riskDimension":"DATA"},
     {"title":"广告主:联合利华","severity":"LOW","riskDimension":"PARTY"}],
    ["品牌安全赔偿有合理上限"],3,"MIXED","快消/互联网","EASY","NONE",0,0),

  C("CP-018","综合-酒店管理+品牌+业绩(EASY)",
    """酒店管理合同
业主：三亚海棠湾投资控股有限公司
管理方：万豪国际集团
品牌：三亚海棠湾喜来登(450间)
期限：初始15年+管理方可选续约10年
管理费：基本(客房3%+餐饮2%)+激励(GOP 8%)
业绩测试：RevPAR连续2年低于同级酒店85%，业主可终止——管理方违约金=年均管理费×剩余年限
品牌标准：管理方不定期更新标准手册，业主180天内完成改造(费用业主承担)""",
    [{"title":"品牌标准不定期更新+180天改造限期+费用全由业主:成本不可控","severity":"HIGH","riskDimension":"PAYMENT"},
     {"title":"违约金=年均管理费×剩余年限:对管理方提前终止赔偿过高","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"初始15年+续约10年","severity":"LOW","riskDimension":"TERMINATION"}],
    ["品牌标准更新条款公平"],3,"OPS_MAINTENANCE","酒店/商业地产","EASY","NONE",0,0),

  C("CP-019","综合-卫星发射+保险+ITAR(EASY)",
    """卫星发射服务
客户：北京九天微星科技发展有限公司
发射商：中国长城工业集团有限公司
火箭：长征八号，窗口：2026 Q3
卫星：12颗低轨物联网小卫星
发射费：USD 68,000,000元
保险：发射保险覆盖星箭分离后180天。除外：太阳活动/空间碎片/在轨碰撞→不赔。
ITAR/EAR：因美国原产抗辐射芯片，客户负责申请美国出口许可并承担费用。许可被拒绝则不退已付款。""",
    [{"title":"ITAR/EAR许可被拒:损失全由客户(不退已付款)——风险极高","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"保险除外(太阳活动+空间碎片+碰撞):恰好是最常见小卫星损失原因","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"发射费:USD 68M","severity":"LOW","riskDimension":"AMOUNT"}],
    ["ITAR风险由双方共担","空间碎片碰撞由保险覆盖"],3,"MIXED","航天","EASY","NONE",0,0),

  C("CP-020","综合-电池工厂EPC+供应链(EASY)",
    """电池超级工厂EPC
业主：宁德时代新能源科技股份有限公司
总包：中国寰球工程有限公司
形式：交钥匙(LSTK)
地点：匈牙利德布勒森，年产100GWh
总价：EUR 7,350,000,000元
工期：2025.11.1开工→2028.10.31机械竣工(36月)→2029.4.30前性能考核移交
违约金:工期延误EUR 1,000,000元/天(上限15%≈EUR 11亿)；良率<93%减收5%+免费整改；每起工亡EUR 5,000,000元无上限
法律：瑞士法，ICC巴黎仲裁(英文)""",
    [{"title":"工期违约金EUR 1M/天极高(上限15%≈11亿)","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"安全违约金无上限:每起工亡EUR 5M——36月大型工程风险不可控","severity":"HIGH","riskDimension":"LIABILITY"},
     {"title":"瑞士法+巴黎仲裁:仲裁地与双方均无关，成本极高","severity":"MEDIUM","riskDimension":"DISPUTE"},
     {"title":"业主:宁德时代,总价:EUR 73.5亿","severity":"LOW","riskDimension":"AMOUNT"},
     {"title":"开工:2025-11-01,机械竣工:2028-10-31(36月)","severity":"LOW","riskDimension":"DATE"}],
    ["安全违约金有上限"],5,"MIXED","新能源/制造","EASY","NONE",1,0),
]

ALL = [("CONTRACT_REVIEW",REVIEW),("INTAKE",INTAKE),("FULFILLMENT_TIMELINE",TIMELINE),
       ("FULFILLMENT_CHECK",CHECK),("COMPREHENSIVE",COMPREHENSIVE)]

def main():
    # Safety gate — prevent accidental runs
    if os.getenv("EVAL_SEED_CONFIRM") != "yes":
        print("SAFETY GATE: Set EVAL_SEED_CONFIRM=yes to actually seed the database.")
        print(f"  Would connect to {DB['host']}:{DB['port']}/{DB['database']} as {DB['user']}")
        print(f"  Would seed {len(DS)} datasets, {sum(len(dict(ALL)[ct]) for ct in dict(ALL))} cases")
        print(f"  Clear mode: {'yes' if os.getenv('EVAL_SEED_CLEAR', 'yes') == 'yes' else 'no (append)'}")
        print("\n  EVAL_SEED_CONFIRM=yes PYTHONIOENCODING=utf-8 python scripts/seed_eval_datasets.py")
        sys.exit(0)

    conn = pymysql.connect(**DB)
    c = conn.cursor()
    try:
        if os.getenv("EVAL_SEED_CLEAR", "yes") == "yes":
            print("Clearing existing eval data...")
            c.execute("DELETE FROM agent_eval_result")
            c.execute("DELETE FROM agent_eval_run")
            c.execute("DELETE FROM agent_eval_case")
            c.execute("DELETE FROM agent_eval_dataset")
            conn.commit()
            print("Cleared.\n")
        else:
            print("Append mode — skipping CLEAR.\n")

        all_data = dict(ALL)
        for ds in DS:
            ct = ds["contract_type"]
            cases = all_data[ct]
            print(f"Creating: {ds['name']} ({ct}) — {len(cases)} cases")
            c.execute("""INSERT INTO agent_eval_dataset (name,version,description,contract_type,case_count,status)
                         VALUES (%s,%s,%s,%s,%s,'ACTIVE')""",
                      (ds["name"],ds["version"],ds["desc"],ct,len(cases)))
            ds_id = c.lastrowid
            conn.commit()
            print(f"  Dataset ID: {ds_id}")

            for (key,title,text,exp,nf,cite,sc,ind,diff,noise,cc,pc) in cases:
                c.execute("""INSERT INTO agent_eval_case
                    (dataset_id,case_key,title,contract_type,contract_text,
                     expected_findings_json,should_not_find_json,expected_citation_count,
                     scenario,industry,difficulty,noise_level,
                     must_have_contract_citation,must_have_policy_citation,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE')""",
                    (ds_id,key,title,ct,text,exp,nf,cite,sc,ind,diff,noise,cc,pc))
            conn.commit()
            print(f"  ✓ {len(cases)} cases inserted\n")

        print(f"Done — {len(DS)} datasets, {sum(len(all_data[ct]) for ct in all_data)} cases total.")
    finally:
        c.close(); conn.close()

if __name__=="__main__":
    main()
