window.SCORING_ANCHORS = [
  {
    "key": "likelihood",
    "label": "发生可能性",
    "rows": [
      {
        "score": 1,
        "anchor": "同行业 5 年内无案例，控制健全且经测试",
        "source": "COSO ERM 2017"
      },
      {
        "score": 2,
        "anchor": "同行业偶发，本企业 3~5 年内无案例",
        "source": "—"
      },
      {
        "score": 3,
        "anchor": "本企业 1~2 年内发生过苗头或一般性问题",
        "source": "内审发现/监管通报"
      },
      {
        "score": 4,
        "anchor": "本企业年内已发生，或同行业高发",
        "source": "ACFE：年均约 5% 营收流失于舞弊"
      },
      {
        "score": 5,
        "anchor": "已多次发生或正在发生，控制基本失效",
        "source": "—"
      }
    ]
  },
  {
    "key": "imp_financial",
    "label": "经济损失（国资委资产损失分级 + 493 号令）",
    "rows": [
      {
        "score": 1,
        "anchor": "<100 万元：未达“一般资产损失”",
        "source": "国资委办法（一般以下）"
      },
      {
        "score": 2,
        "anchor": "100~500 万元：一般资产损失",
        "source": "国资委办法"
      },
      {
        "score": 3,
        "anchor": "500~5000 万元：较大资产损失；较大事故损失区间",
        "source": "国资委办法；493 号令"
      },
      {
        "score": 4,
        "anchor": "5000 万~1 亿元：重大资产损失；重大事故量级",
        "source": "国资委办法；493 号令"
      },
      {
        "score": 5,
        "anchor": "≥1 亿元：特别重大事故量级，危及企业生存",
        "source": "493 号令第三条"
      }
    ]
  },
  {
    "key": "imp_compliance",
    "label": "合规法律（个保法/数安法/GDPR + 不良后果三档）",
    "rows": [
      {
        "score": 1,
        "anchor": "制度瑕疵，责令整改，无外部后果",
        "source": "—"
      },
      {
        "score": 2,
        "anchor": "责令限期整改；罚款 <100 万元",
        "source": "个保法第 66 条第一款"
      },
      {
        "score": 3,
        "anchor": "一般行政处罚 100~1000 万元；责任人被处分",
        "source": "数安法第 45 条"
      },
      {
        "score": 4,
        "anchor": "情节严重 1000~5000 万或营业额 5%（GDPR 顶格同档）",
        "source": "个保法第 66 条第二款；GDPR"
      },
      {
        "score": 5,
        "anchor": "刑事移送、停业/吊照；影响社会与国家层面",
        "source": "国资委重大不良后果；刑法/监察法"
      }
    ]
  },
  {
    "key": "imp_operation",
    "label": "运营中断（493 号令事故等级 + ISO 22301 RTO）",
    "rows": [
      {
        "score": 1,
        "anchor": "局部受阻，当日恢复（RTO<8h）",
        "source": "ISO 22301"
      },
      {
        "score": 2,
        "anchor": "单部门中断，RTO 1~3 天",
        "source": "ISO 22301"
      },
      {
        "score": 3,
        "anchor": "跨部门中断，RTO 3~30 天；或“一般事故”",
        "source": "493 号令第三条"
      },
      {
        "score": 4,
        "anchor": "核心业务瘫痪 1~6 个月；或较大/重大事故量级",
        "source": "493 号令第三条"
      },
      {
        "score": 5,
        "anchor": "集团级瘫痪超 6 个月；或特别重大事故",
        "source": "493 号令第三条"
      }
    ]
  },
  {
    "key": "imp_reputation",
    "label": "声誉舆情（国资委不良后果三档 × 传播层级）",
    "rows": [
      {
        "score": 1,
        "anchor": "无外部感知，仅内部知晓",
        "source": "—"
      },
      {
        "score": 2,
        "anchor": "个别投诉、本地媒体报道，影响限于涉事企业",
        "source": "一般不良后果"
      },
      {
        "score": 3,
        "anchor": "行业内流传、省级媒体/监管通报",
        "source": "较大不良后果"
      },
      {
        "score": 4,
        "anchor": "全国性报道、上级通报批评、资本市场负面反应",
        "source": "较大~重大不良后果"
      },
      {
        "score": 5,
        "anchor": "国家级点名、社会舆论事件、行业整顿",
        "source": "重大不良后果"
      }
    ]
  },
  {
    "key": "imp_fraud",
    "label": "舞弊风险（ACFE 2024 基准 + 职务犯罪管辖）",
    "rows": [
      {
        "score": 1,
        "anchor": "无诱因，职责分离健全经测试，无案例",
        "source": "COSO；ISO 37001"
      },
      {
        "score": 2,
        "anchor": "一般诱因但控制可见；潜在损失 <100 万元",
        "source": "ACFE：中位 $14.5 万"
      },
      {
        "score": 3,
        "anchor": "诱因集中；潜在损失 100~500 万元",
        "source": "ACFE：75 分位 $75 万"
      },
      {
        "score": 4,
        "anchor": "诱因高危或有案例；潜在损失 500~5000 万元",
        "source": "国资委较大~重大档"
      },
      {
        "score": 5,
        "anchor": "系统性舞弊土壤；潜在损失 ≥5000 万或 ≥年营收 5%",
        "source": "ACFE：年均 5% 营收"
      }
    ]
  },
  {
    "key": "imp_strategy",
    "label": "战略影响（COSO ERM + 央企指引战略风险）",
    "rows": [
      {
        "score": 1,
        "anchor": "对战略目标无偏离影响",
        "source": "COSO ERM 2017"
      },
      {
        "score": 2,
        "anchor": "影响单项年度 KPI，可内部消化",
        "source": "COSO ERM 战略类"
      },
      {
        "score": 3,
        "anchor": "影响年度重点战略举措推进",
        "source": "央企指引战略风险"
      },
      {
        "score": 4,
        "anchor": "影响三年规划目标或主营业务布局",
        "source": "COSO：战略与绩效"
      },
      {
        "score": 5,
        "anchor": "颠覆战略目标/主营业务模式重构",
        "source": "央企指引：战略风险重大"
      }
    ]
  },
  {
    "key": "imp_data",
    "label": "数据安全（数安法分级 + ISO 27001 CIA）",
    "rows": [
      {
        "score": 1,
        "anchor": "不涉及敏感数据",
        "source": "ISO 27001"
      },
      {
        "score": 2,
        "anchor": "少量内部非敏数据受损，可恢复",
        "source": "网数条例第 57 条"
      },
      {
        "score": 3,
        "anchor": "一般个人信息或商业数据泄露（<10 万条）",
        "source": "个保法第 66 条第一款"
      },
      {
        "score": 4,
        "anchor": "大量个人信息/重要数据泄露或出境违规",
        "source": "个保法顶格；数安法第 45 条"
      },
      {
        "score": 5,
        "anchor": "重要数据泄露危害国家安全/公共安全",
        "source": "数安法：重大违规"
      }
    ]
  },
  {
    "key": "imp_hse",
    "label": "健康安全（ISO 45001 + 安全生产法 + 493 号令）",
    "rows": [
      {
        "score": 1,
        "anchor": "无人员伤害可能",
        "source": "ISO 45001"
      },
      {
        "score": 2,
        "anchor": "轻微伤风险，职业健康隐患",
        "source": "ISO 45001"
      },
      {
        "score": 3,
        "anchor": "重伤风险；一般事故苗头（<3 人死亡）",
        "source": "493 号令一般事故"
      },
      {
        "score": 4,
        "anchor": "死亡 3~30 人或重伤 10~100 人量级",
        "source": "493 号令较大/重大事故"
      },
      {
        "score": 5,
        "anchor": "群死群伤（≥30 人死亡）或特别重大事故",
        "source": "493 号令特别重大"
      }
    ]
  }
];
