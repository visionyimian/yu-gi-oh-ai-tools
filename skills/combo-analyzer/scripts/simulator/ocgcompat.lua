--[[
脚本兼容层：补齐「卡脚本要用、但当前 ocgcore 没注册」的判定函数。

两个版本的核心差别很大：edo9300 版 ocgcore 的 libcard.cpp 里没有这些函数，
而 mycard/ygopro-scripts 的卡脚本把它们当引擎 API 用（例如
`aux.AddLinkProcedure(c, aux.FilterBoolFunction(Card.IsLinkType, TYPE_EFFECT), 2)`）。
后果比「报错」隐蔽得多：素材过滤函数在判定那一刻抛 lua 错误，引擎把这次召唤
当成不可用，于是额外卡组召唤根本不出现在 MSG_SELECT_IDLECMD 的 spsummon 段里——
现象是「场上素材够了，却始终不给连接召唤」。

每一段都带 `if X==nil` 守卫：换成自带这些函数的核心（mycard/ygopro-core）时
一个字都不会覆盖，日志里也不会出现重复定义。

命名规律：`IsLinkX` / `IsFusionX` 是「作为连接 / 融合素材时」的判定，语义等于
对应的基础判定；`IsAllTypes` 是 `IsType` 的「全部位都命中」版本（`IsType` 是任一位）。
]]

-- 作为连接素材时的类型 / 种族 / 字段 / 卡号判定
if Card.IsLinkType==nil then
	function Card.IsLinkType(c,t) return c:IsType(t) end
end
if Card.IsLinkRace==nil then
	function Card.IsLinkRace(c,r) return c:IsRace(r) end
end
if Card.IsLinkSetCard==nil then
	function Card.IsLinkSetCard(c,sc) return c:IsSetCard(sc) end
end
if Card.GetLinkCode==nil then
	function Card.GetLinkCode(c) return c:GetCode() end
end

-- 作为融合素材时的同一套判定
if Card.IsFusionType==nil then
	function Card.IsFusionType(c,t) return c:IsType(t) end
end
if Card.IsFusionAttribute==nil then
	function Card.IsFusionAttribute(c,a) return c:IsAttribute(a) end
end
if Card.IsFusionSetCard==nil then
	function Card.IsFusionSetCard(c,sc) return c:IsSetCard(sc) end
end
if Card.IsFusionCode==nil then
	function Card.IsFusionCode(c,code) return c:IsCode(code) end
end
if Card.GetFusionAttribute==nil then
	function Card.GetFusionAttribute(c) return c:GetAttribute() end
end
if Card.GetFusionCode==nil then
	function Card.GetFusionCode(c) return c:GetCode() end
end

-- 类型位全部命中：IsType(TYPE_FUSION+TYPE_SYNCHRO) 是「任一」，这个要求全在
if Card.IsAllTypes==nil then
	function Card.IsAllTypes(c,t) return c:GetType()&t==t end
end

-- 表侧：场上按正面表示算；墓地的卡没有「里侧」，除外区的卡要看是否正面朝上
if Card.IsFaceupEx==nil then
	function Card.IsFaceupEx(c)
		return c:IsFaceup() or c:IsLocation(LOCATION_GRAVE)
			or (c:IsLocation(LOCATION_REMOVED) and c:IsPosition(POS_FACEUP))
	end
end

-- 超量素材判定在新版里的名字
if Card.IsCanOverlay==nil then
	function Card.IsCanOverlay(c) return c:IsCanBeXyzMaterial() end
end

-- 「必须作为连接素材」的卡：本版没有这个查询，等价于「一张都没有」。
-- 连接素材判定必经此处，缺了它 LinkCondition 会直接抛错。
if Duel.GetMustMaterial==nil then
	function Duel.GetMustMaterial(tp,code) return Group.CreateGroup() end
end

-- 正在结算的那一环的目标：旧名字是 GetChainInfo(0, CHAININFO_TARGET_CARDS)
if Duel.GetTargetsRelateToChain==nil then
	function Duel.GetTargetsRelateToChain()
		local g=Duel.GetChainInfo(0,CHAININFO_TARGET_CARDS)
		return g or Group.CreateGroup()
	end
end
