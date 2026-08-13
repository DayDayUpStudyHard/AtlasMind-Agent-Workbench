#!/usr/bin/env python3
"""Seed the Golden Dataset v1 — regression cases from Phase 0 (PRD §25.4).

Each case maps to one historical regression:

  GD-IN-001  合同总价被识别成 10 CNY        (金额"10"陷阱：10台/10万单价/10%干扰)
  GD-IN-002  合同标题、甲乙方识别错误        (项目业主/联系人/开户行≠合同当事人)
  GD-TL-001  合同结束条件被错误转为固定日期  (履行完毕之日=条件事件)
  GD-TL-002  时间节点截断/尾部信息丢失      (长条款末尾的付款期限)
  GD-RV-001  补充检索未修正结论            (付款条款引用附件，风险藏在附件细则)
  GD-RV-002  "未找到验收条款"规则发现缺少解释 (缺条款合同，规则发现须带处置建议)

Safety: set GOLDEN_SEED_CONFIRM=yes to run. Append-only by default — golden
datasets never clear existing eval data (unlike seed_eval_datasets.py).

Usage:
  GOLDEN_SEED_CONFIRM=yes PYTHONIOENCODING=utf-8 python scripts/seed_golden_datasets.py
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
  {"name":"Golden-风险审查回归集","version":"golden-v1","contract_type":"CONTRACT_REVIEW",
   "desc":"Phase 0 Golden Dataset：跨条款引用隐藏风险、缺失条款规则发现解释。来源 PRD §25.4 回归清单。"},
  {"name":"Golden-要素提取回归集","version":"golden-v1","contract_type":"INTAKE",
   "desc":"Phase 0 Golden Dataset：金额歧义(10 CNY 陷阱)、甲乙方与项目业主/联系人混淆。来源 PRD §25.4 回归清单。"},
  {"name":"Golden-履约日程回归集","version":"golden-v1","contract_type":"FULFILLMENT_TIMELINE",
   "desc":"Phase 0 Golden Dataset：结束条件不得转为固定日期、长条款尾部节点截断。来源 PRD §25.4 回归清单。"},
]

def C(key,title,text,exp,nf,cite=0,sc="",ind="",diff="",noise="NONE",cc=0,pc=0):
  return (key,title,text.strip(),json.dumps(exp,ensure_ascii=False),json.dumps(nf,ensure_ascii=False),cite,sc,ind,diff,noise,cc,pc)

GOLDEN = {
  "CONTRACT_REVIEW": [
    # GD-RV-001 回归：补充检索未修正结论 / 风险藏在附件细则，付款条款仅引用附件
    C("GD-RV-001","回归-付款条款引用附件隐藏验收风险(CROSS_REF)",
      """设备采购合同
甲方：上海电气集团股份有限公司
乙方：苏州汇川技术股份有限公司
第七条 付款
7.1 设备到货安装调试完成后，甲方按本合同附件三《验收细则》组织验收，验收合格后30日内支付合同总价款的40%。
7.2 质保金为合同总价款的5%，质保期满且无质量异议后15日内支付。
附件三 验收细则
A3.1 设备验收以甲方指定人员的主观满意度为准，甲方有权在不说明理由的情况下拒绝验收。
A3.2 乙方对验收结果有异议的，以甲方意见为准；乙方不得因验收争议暂停售后服务。""",
      [{"title":"验收以甲方指定人员主观满意度为准且可无理由拒收，乙方无客观验收标准与异议救济","severity":"HIGH","riskDimension":"ACCEPTANCE"},
       {"title":"以甲方意见为准条款剥夺乙方异议权利，验收标准实质虚置","severity":"HIGH","riskDimension":"ACCEPTANCE"}],
      ["验收标准客观明确"],2,"GOODS_PURCHASE","智能制造","CROSS_REF","NONE",1,0),

    # GD-RV-002 回归：规则发现"未找到验收条款"须附带解释与处置建议
    C("GD-RV-002","回归-缺验收条款规则发现须有解释(MISSING_CLAUSE)",
      """软件许可合同
甲方：携程计算机技术(上海)有限公司
乙方：杭州虹软科技股份有限公司
第一条 许可内容
1.1 乙方授权甲方使用其图像识别算法组件，许可期限3年。
第二条 许可费
2.1 许可费总额人民币90万元，签订后一次性支付。
第三条 交付
3.1 乙方在签订后15日内交付部署包及技术文档。
(合同全文共8页，无验收条款、无交付标准条款、无功能说明条款)""",
      [{"title":"合同未约定验收条款与交付标准，甲方付款后无验收抓手","severity":"HIGH","riskDimension":"ACCEPTANCE"}],
      ["验收条款完整且可执行"],0,"SOFTWARE_IT","互联网","MISSING_CLAUSE","NONE",0,1),
  ],

  "INTAKE": [
    # GD-IN-001 回归：合同总价被识别成 10 CNY（"10"陷阱）
    C("GD-IN-001","回归-金额10陷阱(AMOUNT_AMBIGUITY)",
      """监控设备采购合同
甲方：杭州海康威视数字技术股份有限公司
乙方：深圳市大族激光科技股份有限公司
第一条 设备与价格
1.1 本合同项下设备共计10台，单价人民币10万元/台，合同总价人民币100万元整。
1.2 设备质保金为合同总价的10%，质保期满后无息退还。
1.3 乙方逾期交货的，每日按合同总价的0.1%支付违约金，累计不超过合同总价的10%。
第二条 付款
2.1 甲方于签订后10日内支付合同总价的30%，到货验收后10日内支付60%，尾款10%于质保期满后支付。""",
      [{"title":"甲方:杭州海康威视数字技术股份有限公司","severity":"LOW","riskDimension":"PARTY"},
       {"title":"乙方:深圳市大族激光科技股份有限公司","severity":"LOW","riskDimension":"PARTY"},
       {"title":"总价:100万元","severity":"LOW","riskDimension":"PAYMENT"},
       {"title":"单价:10万元/台×10台","severity":"LOW","riskDimension":"PAYMENT"}],
      ["合同总价为10元","单价为10元"],4,"GOODS_PURCHASE","安防","AMOUNT_AMBIGUITY","NONE",0,0),

    # GD-IN-002 回归：标题、甲乙方识别错误（项目业主/联系人/开户行≠当事人）
    C("GD-IN-002","回归-甲乙方与项目业主混淆(PARTY_AMBIGUITY)",
      """城市管理信息平台合作协议
甲方（采购人）：XX市城市管理局
乙方（服务方）：XX环保科技股份有限公司
乙方联系人：王小明（联系电话：13800000000）
乙方开户行：中国银行XX支行，账号：6217000000000000000
第三条 项目背景
3.1 本项目业主为XX市水务集团，由甲方委托乙方建设智慧环卫管理平台。
3.2 项目业主不承担本合同项下任何付款义务，付款义务由甲方承担。
(注：项目业主≠甲方；联系人、开户行≠乙方名称)""",
      [{"title":"甲方:XX市城市管理局","severity":"LOW","riskDimension":"PARTY"},
       {"title":"乙方:XX环保科技股份有限公司","severity":"LOW","riskDimension":"PARTY"},
       {"title":"付款义务方:甲方(XX市城市管理局)，项目业主不付款","severity":"MEDIUM","riskDimension":"PAYMENT"}],
      ["甲方:XX市水务集团","乙方:王小明"],3,"SERVICE_PROCUREMENT","政府/环保","PARTY_AMBIGUITY","NONE",0,0),
  ],

  "FULFILLMENT_TIMELINE": [
    # GD-TL-001 回归：合同结束条件被错误转为固定日期
    C("GD-TL-001","回归-结束条件不得转固定日期(CONDITIONAL_END)",
      """物业服务合同
甲方：XX市阳光花园业主委员会
乙方：XX物业管理有限公司
第五条 合同期限
5.1 本合同自2026年1月1日起生效。
5.2 本合同至双方物业服务权利义务全部履行完毕之日终止。
5.3 业主委员会另行聘请物业服务企业且交接工作全部完成的，本合同提前终止。
第八条 物业费
8.1 物业费按建筑面积每平方米每月2.8元计收，乙方每月5日前向业主公示上月收支明细。""",
      [{"title":"生效:2026-01-01","severity":"LOW","riskDimension":"DATE"},
       {"title":"终止:双方权利义务履行完毕之日(条件事件)","severity":"LOW","riskDimension":"DATE"},
       {"title":"提前终止:新聘物业企业且交接完成(双条件)","severity":"LOW","riskDimension":"DATE"},
       {"title":"每月5日前:公示收支明细(周期)","severity":"LOW","riskDimension":"PAYMENT"}],
      ["合同终止日期为2027-12-31","合同终止日期为2028-01-01"],4,"SERVICE_PROCUREMENT","物业管理","CONDITIONAL_END","NONE",0,0),

    # GD-TL-002 回归：时间节点截断/尾部信息丢失
    C("GD-TL-002","回归-长条款尾部付款期限截断(TAIL_TRUNCATION)",
      """系统集成服务合同
甲方：中国电信股份有限公司XX分公司
乙方：XX信息技术有限公司
第六条 结算方式
6.1 乙方完成全部集成实施并提交完整的竣工资料、测试报告、操作手册、培训记录及第三方检测合格证明，且经甲方组织验收并在验收报告上签字确认后，视为交付完成；甲方自交付完成之日起10日内向乙方支付合同总价款的90%；剩余10%作为质保金，自交付完成之日起满12个月且期间未发生重大质量问题的，甲方在15日内一次性无息支付给乙方。""",
      [{"title":"交付完成:甲方验收签字确认(条件事件)","severity":"LOW","riskDimension":"MILESTONE"},
       {"title":"90%款:交付完成后10日内","severity":"LOW","riskDimension":"PAYMENT"},
       {"title":"质保金10%:交付完成后12个月+15日内","severity":"LOW","riskDimension":"PAYMENT"}],
      [],3,"SOFTWARE_IT","电信","TAIL_TRUNCATION","NONE",0,0),
  ],
}

def main():
    if os.getenv("GOLDEN_SEED_CONFIRM") != "yes":
        print("SAFETY GATE: Set GOLDEN_SEED_CONFIRM=yes to actually seed the database.")
        print(f"  Would connect to {DB['host']}:{DB['port']}/{DB['database']} as {DB['user']}")
        print(f"  Would seed {len(DS)} golden datasets, {sum(len(GOLDEN[d['contract_type']]) for d in DS)} cases (append-only)")
        print("\n  GOLDEN_SEED_CONFIRM=yes PYTHONIOENCODING=utf-8 python scripts/seed_golden_datasets.py")
        sys.exit(0)

    conn = pymysql.connect(**DB)
    c = conn.cursor()
    try:
        for ds in DS:
            ct = ds["contract_type"]
            cases = GOLDEN[ct]
            print(f"Creating: {ds['name']} ({ct}) — {len(cases)} cases")
            c.execute("""INSERT INTO agent_eval_dataset (name,version,description,contract_type,case_count,status)
                         VALUES (%s,%s,%s,%s,%s,'ACTIVE')""",
                      (ds["name"], ds["version"], ds["desc"], ct, len(cases)))
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
            print(f"  OK {len(cases)} cases inserted\n")
        print(f"Done — {len(DS)} golden datasets seeded (append-only).")
    finally:
        c.close(); conn.close()

if __name__ == "__main__":
    main()
