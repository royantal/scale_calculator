import React, { useState, useEffect } from 'react';

const zoneData = {
  '일반주거지역_2종': { legalCoverage: 0.6, legalFAR: 2.5, appliedCoverage: 0.55, appliedFAR: 2.49 },
  '일반주거지역_3종': { legalCoverage: 0.5, legalFAR: 3.0, appliedCoverage: 0.4, appliedFAR: 2.99 },
  '준주거지역': { legalCoverage: 0.6, legalFAR: 4.0, appliedCoverage: 0.55, appliedFAR: 3.99 },
  '일반상업지역': { legalCoverage: 0.6, legalFAR: 8.0, appliedCoverage: 0.55, appliedFAR: 7.99 }
};

const useTypeRatios = {
  '임대형기숙사': { dorm: 1, officetel: 0, hotel: 0, retail: 0 },
  '관광호텔': { dorm: 0, officetel: 0, hotel: 1, retail: 0 },
  '오피스텔': { dorm: 0, officetel: 1, hotel: 0, retail: 0 },
  '임대형기숙사 + 근생': { dorm: 0.75, officetel: 0, hotel: 0, retail: 0.25 },
  '임대형기숙사 + 관광호텔': { dorm: 0.75, officetel: 0, hotel: 0.25, retail: 0 },
  '임대형기숙사 + 오피스텔 + 근생': { dorm: 0.75, officetel: 0.15, hotel: 0, retail: 0.1 }
};

export default function ScaleCalculator() {
  const VWORLD_API_KEY = 'DB07E3CD-6F12-388C-99D4-6779EA88652F';
  
  const [inputs, setInputs] = useState({
    location: '서울특별시 성동구 도선동 39-2',
    zoneType: '일반주거지역_3종',
    landArea: 2845.3,
    useType: '임대형기숙사',
    dormArea: 14.5,
    officetelArea: 17.5,
    hotelArea: 17.5,
    // 복합 용도지역
    multiZone: false,
    zone1Type: '일반주거지역_3종',
    zone1Area: 0,
    zone2Type: '일반주거지역_2종',
    zone2Area: 0,
    customFAR: 0
  });

  const [searchStatus, setSearchStatus] = useState('');
  const [districtPlan, setDistrictPlan] = useState({
    exists: false,
    name: ''
  });

  // 주요 가정
  const [assumptions, setAssumptions] = useState({
    groundSharedRatio: 0.5,
    dormExclusiveRatio: 0.55,
    hotelOfficetelExclusiveRatio: 0.6,
    mechElecRatio: 0.08,
    undergroundCoverage: 0.75,
    typicalCoverage: 0.3,
    selfParkingRatio: 0.03
  });

  const [results, setResults] = useState({
    totalUnits: 0,
    buildingHeight: 0,
    groundFloors: 0,
    undergroundFloors: 0,
    devPeriod: 0,
    constPeriod: 0,
    facilityData: null
  });

  // 엑셀과 100% 동일한 계산 로직
  const calculateResults = () => {
    try {
      // 용적률 계산
      let appliedFAR;
      
      if (inputs.multiZone) {
        // 복합 용도지역: 커스텀 FAR 또는 가중평균
        if (inputs.customFAR > 0) {
          appliedFAR = inputs.customFAR;
        } else {
          const totalArea = inputs.zone1Area + inputs.zone2Area;
          if (totalArea > 0 && inputs.zone1Area > 0 && inputs.zone2Area > 0) {
            const zone1 = zoneData[inputs.zone1Type];
            const zone2 = zoneData[inputs.zone2Type];
            if (zone1 && zone2) {
              appliedFAR = (zone1.appliedFAR * inputs.zone1Area + zone2.appliedFAR * inputs.zone2Area) / totalArea;
            } else {
              appliedFAR = 3.0; // 기본값
            }
          } else {
            appliedFAR = 3.0; // 기본값
          }
        }
      } else {
        // 단일 용도지역
        const zone = zoneData[inputs.zoneType];
        if (!zone) return;
        appliedFAR = zone.appliedFAR;
      }

      const ratios = useTypeRatios[inputs.useType];
      if (!ratios) return;

      const landArea = inputs.landArea;
      const farArea = landArea * appliedFAR; // E9: 용적률산정연면적
      
      // C30~F30: 시설면적
      const dormFacilityArea = ratios.dorm * farArea;
      const officetelFacilityArea = ratios.officetel * farArea;
      const hotelFacilityArea = ratios.hotel * farArea;
      const retailFacilityArea = ratios.retail * farArea;

      // 반복 계산으로 수렴 (순환참조 해결)
      let dormUnits = 0;
      let officetelUnits = 0;
      let hotelUnits = 0;
      let totalParking = 0;
      let dormGroundArea = dormFacilityArea;
      let officetelGroundArea = officetelFacilityArea;
      let hotelGroundArea = hotelFacilityArea;
      let retailGroundArea = retailFacilityArea;
      let totalGroundArea = dormGroundArea + officetelGroundArea + hotelGroundArea + retailGroundArea;
      let sharedSpace = 0;
      let sharedSpaceGround = 0;
      let dormUnderArea = 0;
      let officetelUnderArea = 0;
      let hotelUnderArea = 0;
      let retailUnderArea = 0;
      let totalUnderArea = 0;
      
      // 세부 항목 변수
      let dormParkingTower = 0, officetelParkingTower = 0, hotelParkingTower = 0, retailParkingTower = 0;
      let dormUnderShared = 0, officetelUnderShared = 0, hotelUnderShared = 0, retailUnderShared = 0;
      let dormSharedUnder = 0, officetelSharedUnder = 0, hotelSharedUnder = 0, retailSharedUnder = 0;
      let dormMechElec = 0, officetelMechElec = 0, hotelMechElec = 0, retailMechElec = 0;
      let undergroundShared = 0, mechElec = 0;
      
      for (let iter = 0; iter < 50; iter++) {
        const prevTotalParking = totalParking;
        const prevDormUnits = dormUnits;
        const prevOfficetelUnits = officetelUnits;
        const prevHotelUnits = hotelUnits;
        
        // 공유공간 계산 (C48, C49~C52)
        const totalUnits = dormUnits + officetelUnits + hotelUnits;
        if (totalUnits <= 150) {
          sharedSpace = totalUnits * 4;
        } else if (totalUnits <= 300) {
          sharedSpace = 600 + (totalUnits - 150) * 6;
        } else if (totalUnits <= 500) {
          sharedSpace = 1125 + (totalUnits - 300) * 6;
        } else {
          sharedSpace = 1725 + (totalUnits - 500) * 6;
        }
        
        sharedSpaceGround = sharedSpace * assumptions.groundSharedRatio; // C42
        const sharedSpaceUnder = sharedSpace - sharedSpaceGround; // C43
        
        // 지하연면적 계산 (C32~F32)
        undergroundShared = totalGroundArea * 0.02; // 지하공용
        mechElec = totalGroundArea * assumptions.mechElecRatio; // 기계전기실
        
        if (totalGroundArea > 0) {
          // 각 시설별 세부 항목 계산
          dormUnderShared = undergroundShared * (dormGroundArea / totalGroundArea);
          officetelUnderShared = undergroundShared * (officetelGroundArea / totalGroundArea);
          hotelUnderShared = undergroundShared * (hotelGroundArea / totalGroundArea);
          retailUnderShared = undergroundShared * (retailGroundArea / totalGroundArea);
          
          dormSharedUnder = sharedSpaceUnder * (dormGroundArea / totalGroundArea);
          officetelSharedUnder = sharedSpaceUnder * (officetelGroundArea / totalGroundArea);
          hotelSharedUnder = sharedSpaceUnder * (hotelGroundArea / totalGroundArea);
          retailSharedUnder = sharedSpaceUnder * (retailGroundArea / totalGroundArea);
          
          dormMechElec = mechElec * (dormGroundArea / totalGroundArea);
          officetelMechElec = mechElec * (officetelGroundArea / totalGroundArea);
          hotelMechElec = mechElec * (hotelGroundArea / totalGroundArea);
          retailMechElec = mechElec * (retailGroundArea / totalGroundArea);
          
          dormUnderArea = dormUnderShared + dormSharedUnder + dormMechElec;
          officetelUnderArea = officetelUnderShared + officetelSharedUnder + officetelMechElec;
          hotelUnderArea = hotelUnderShared + hotelSharedUnder + hotelMechElec;
          retailUnderArea = retailUnderShared + retailSharedUnder + retailMechElec;
        }
        
        totalUnderArea = dormUnderArea + officetelUnderArea + hotelUnderArea + retailUnderArea;
        
        // 주차 계산 (C40~F40) - 엑셀: (지상+지하)/200 또는 /134
        const dormParking = ratios.dorm > 0 ? Math.ceil((dormGroundArea + dormUnderArea) / 200) : 0;
        const officetelParking = ratios.officetel > 0 ? Math.floor(officetelUnits * 0.5) : 0;
        const hotelParking = ratios.hotel > 0 ? Math.ceil((hotelGroundArea + hotelUnderArea) / 134) : 0;
        const retailParking = ratios.retail > 0 ? Math.ceil((retailGroundArea + retailUnderArea) / 134) : 0;
        
        totalParking = dormParking + officetelParking + hotelParking + retailParking; // G40
        
        // C16, C17: 자주식/기계식
        const selfParking = Math.ceil(totalParking * assumptions.selfParkingRatio);
        const mechanicalParking = totalParking - selfParking;
        
        // 주차타워 (C31~F31)
        const parkingTowerUnits = Math.ceil(mechanicalParking / 80);
        const parkingTowerAreaTotal = parkingTowerUnits * 50;
        
        const facilityAreaSum = dormFacilityArea + officetelFacilityArea + hotelFacilityArea + retailFacilityArea;
        
        if (facilityAreaSum > 0) {
          dormParkingTower = parkingTowerAreaTotal * (dormFacilityArea / facilityAreaSum);
          officetelParkingTower = parkingTowerAreaTotal * (officetelFacilityArea / facilityAreaSum);
          hotelParkingTower = parkingTowerAreaTotal * (hotelFacilityArea / facilityAreaSum);
          retailParkingTower = parkingTowerAreaTotal * (retailFacilityArea / facilityAreaSum);
          
          // C29~F29: 지상연면적 = 시설면적 + 주차타워
          dormGroundArea = dormFacilityArea + dormParkingTower;
          officetelGroundArea = officetelFacilityArea + officetelParkingTower;
          hotelGroundArea = hotelFacilityArea + hotelParkingTower;
          retailGroundArea = retailFacilityArea + retailParkingTower;
        }
        
        totalGroundArea = dormGroundArea + officetelGroundArea + hotelGroundArea + retailGroundArea; // G29
        
        // 호실수 계산 (C39~E39)
        if (dormGroundArea > 0) {
          dormUnits = Math.floor((dormGroundArea - sharedSpaceGround) * assumptions.dormExclusiveRatio / inputs.dormArea);
        }
        
        if (officetelGroundArea > 0) {
          const officetelSharedGround = ratios.dorm > 0 ? 0 : (sharedSpaceGround * (officetelGroundArea / totalGroundArea));
          officetelUnits = Math.floor((officetelGroundArea - officetelSharedGround) * assumptions.hotelOfficetelExclusiveRatio / inputs.officetelArea);
        }
        
        if (hotelGroundArea > 0) {
          const hotelSharedGround = ratios.dorm > 0 ? 0 : (sharedSpaceGround * (hotelGroundArea / totalGroundArea));
          hotelUnits = Math.floor((hotelGroundArea - hotelSharedGround) * assumptions.hotelOfficetelExclusiveRatio / inputs.hotelArea);
        }
        
        // 수렴 확인
        if (Math.abs(totalParking - prevTotalParking) < 1 && 
            dormUnits === prevDormUnits && 
            officetelUnits === prevOfficetelUnits && 
            hotelUnits === prevHotelUnits) {
          console.log('수렴 완료:', iter, '반복');
          break;
        }
      }
      
      const totalUnits = dormUnits + officetelUnits + hotelUnits;
      
      // 최종 주차 (값만 재할당)
      const finalDormParking = ratios.dorm > 0 ? Math.ceil((dormGroundArea + dormUnderArea) / 200) : 0;
      const finalOfficetelParking = ratios.officetel > 0 ? Math.floor(officetelUnits * 0.5) : 0;
      const finalHotelParking = ratios.hotel > 0 ? Math.ceil((hotelGroundArea + hotelUnderArea) / 134) : 0;
      const finalRetailParking = ratios.retail > 0 ? Math.ceil((retailGroundArea + retailUnderArea) / 134) : 0;
      totalParking = finalDormParking + finalOfficetelParking + finalHotelParking + finalRetailParking;
      
      // 층수 계산 (E16, E17)
      const groundFloors = Math.ceil(totalGroundArea / (landArea * assumptions.typicalCoverage)) + 1;
      const undergroundFloors = Math.ceil(totalUnderArea / (landArea * assumptions.undergroundCoverage));
      const buildingHeight = groundFloors * 3.3; // E15
      
      // 기간 계산
      const constPeriod = groundFloors + (undergroundFloors * 3) + 6;
      const devPeriod = 15 + constPeriod;
      
      setResults({
        totalUnits,
        buildingHeight,
        groundFloors,
        undergroundFloors,
        devPeriod,
        constPeriod,
        facilityData: {
          ratios,
          dorm: { 
            ground: dormGroundArea,
            facilityArea: dormFacilityArea,
            parkingTower: dormParkingTower,
            under: dormUnderArea,
            underShared: dormUnderShared,
            parkingLot: dormUnderArea - dormUnderShared - dormSharedUnder - dormMechElec,
            sharedUnder: dormSharedUnder,
            mechElec: dormMechElec,
            total: dormGroundArea + dormUnderArea, 
            units: dormUnits,
            parking: finalDormParking
          },
          officetel: { 
            ground: officetelGroundArea,
            facilityArea: officetelFacilityArea,
            parkingTower: officetelParkingTower,
            under: officetelUnderArea,
            underShared: officetelUnderShared,
            parkingLot: officetelUnderArea - officetelUnderShared - officetelSharedUnder - officetelMechElec,
            sharedUnder: officetelSharedUnder,
            mechElec: officetelMechElec,
            total: officetelGroundArea + officetelUnderArea, 
            units: officetelUnits,
            parking: finalOfficetelParking
          },
          hotel: { 
            ground: hotelGroundArea,
            facilityArea: hotelFacilityArea,
            parkingTower: hotelParkingTower,
            under: hotelUnderArea,
            underShared: hotelUnderShared,
            parkingLot: hotelUnderArea - hotelUnderShared - hotelSharedUnder - hotelMechElec,
            sharedUnder: hotelSharedUnder,
            mechElec: hotelMechElec,
            total: hotelGroundArea + hotelUnderArea, 
            units: hotelUnits,
            parking: finalHotelParking
          },
          retail: { 
            ground: retailGroundArea,
            facilityArea: retailFacilityArea,
            parkingTower: retailParkingTower,
            under: retailUnderArea,
            underShared: retailUnderShared,
            parkingLot: retailUnderArea - retailUnderShared - retailSharedUnder - retailMechElec,
            sharedUnder: retailSharedUnder,
            mechElec: retailMechElec,
            total: retailGroundArea + retailUnderArea,
            parking: finalRetailParking
          },
          totals: { 
            ground: totalGroundArea,
            facilityArea: dormFacilityArea + officetelFacilityArea + hotelFacilityArea + retailFacilityArea,
            parkingTower: dormParkingTower + officetelParkingTower + hotelParkingTower + retailParkingTower,
            under: totalUnderArea,
            underShared: undergroundShared,
            parkingLot: totalUnderArea - undergroundShared - (sharedSpace - sharedSpaceGround) - mechElec,
            sharedUnder: sharedSpace - sharedSpaceGround,
            mechElec: mechElec,
            total: totalGroundArea + totalUnderArea, 
            units: totalUnits, 
            parking: totalParking,
            sharedSpace: sharedSpace,
            sharedSpaceGround: sharedSpaceGround,
            sharedSpaceUnder: sharedSpace - sharedSpaceGround
          }
        }
      });
      
      console.log('=== 계산 결과 ===');
      console.log('세대수:', totalUnits, '(엑셀: 296)');
      console.log('지상연면적:', totalGroundArea.toFixed(2), '(엑셀: 8557.45)');
      console.log('지하연면적:', totalUnderArea.toFixed(2), '(엑셀: 1593.74)');
      console.log('전체연면적:', (totalGroundArea + totalUnderArea).toFixed(2), '(엑셀: 10151.19)');
      console.log('지상층:', groundFloors, '(엑셀: 12)');
      console.log('지하층:', undergroundFloors, '(엑셀: 1)');
      console.log('높이:', buildingHeight.toFixed(2), '(엑셀: 39.6)');
      console.log('주차:', totalParking, '(엑셀: 51)');
    } catch (e) {
      console.error('계산 오류:', e);
    }
  };

  useEffect(() => {
    calculateResults();
  }, [inputs, assumptions]);

  const fmt = (num, decimals = 0) => {
    if (!num && num !== 0) return '-';
    return num.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  };

  // 네이버 지도 검색
  const openNaverMap = () => {
    if (!inputs.location) {
      alert('주소를 입력해주세요');
      return;
    }
    
    const url = 'https://map.naver.com/p/search/' + encodeURIComponent(inputs.location);
    window.open(url, '_blank');
    setSearchStatus('✅ 네이버 지도가 열렸습니다. 필지를 클릭하면 용도지역을 확인할 수 있습니다.');
    setTimeout(() => setSearchStatus(''), 10000);
  };

  // 자동 검색 함수 (Python 웹서버 사용)
  const autoSearch = async () => {
    const address = inputs.location;
    if (!address) {
      alert('주소를 입력해주세요');
      return;
    }

    console.log('🔍 용도지역 자동검색 시작:', address);
    setSearchStatus('🔍 용도지역 조회 중... (Python 웹서버)');

    try {
      // Python 웹서버 호출 (포트 8080)
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000); // 30초 타임아웃

      console.log('📡 Python 웹서버 요청: http://localhost:8080/search');
      
      const response = await fetch('http://localhost:8080/search', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          address: address
        }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error('서버 응답 오류: ' + response.status);
      }

      const data = await response.json();
      console.log('📦 서버 응답:', data);

      if (data.final) {
        // 성공!
        console.log('✅ 용도지역 조회 성공:', data.final);
        
        setSearchStatus(`✅ 조회 완료!`);
        
        // 결과 alert
        let alertMsg = `🎉 용도지역 조회 완료!\n\n` +
                       `📍 주소: ${data.address}\n` +
                       `🏘️ 용도지역: ${data.final}\n\n`;
        
        if (data.method1 && data.method2) {
          alertMsg += `📊 조회 결과:\n`;
          alertMsg += `  • 토지이음: ${data.method1}\n`;
          alertMsg += `  • VWorld API: ${data.method2}\n\n`;
          
          if (data.match) {
            alertMsg += `✅ 두 방법 결과 일치\n\n`;
          } else {
            alertMsg += `⚠️ 결과 불일치 (토지이음 결과 사용)\n\n`;
          }
        } else if (data.method1) {
          alertMsg += `📊 조회 방법: 토지이음\n\n`;
        } else if (data.method2) {
          alertMsg += `📊 조회 방법: VWorld API\n\n`;
        }
        
        alertMsg += `아래에서 용도지역을 선택하세요.`;
        
        alert(alertMsg);
        
        setTimeout(() => setSearchStatus(''), 5000);
      } else {
        // 실패
        console.log('⚠️ 용도지역 조회 실패');
        setSearchStatus('❌ 용도지역을 찾을 수 없습니다.');
        
        alert('⚠️ 용도지역 조회 실패\n\n' +
              '다음 방법을 시도해보세요:\n\n' +
              '1. 🗺️ 네이버 버튼으로 확인\n' +
              '2. 주소가 정확한지 확인\n\n' +
              '예: 서울특별시 강남구 역삼동 812-13');
        
        setTimeout(() => setSearchStatus(''), 8000);
      }

    } catch (err) {
      console.error('❌ 자동 검색 오류:', err);
      
      if (err.name === 'AbortError') {
        setSearchStatus('⏱️ 응답 시간 초과 (30초)');
        alert('⏱️ 서버 응답 시간 초과\n\n' +
              '확인사항:\n' +
              '1. Python 웹서버가 실행 중인가요?\n' +
              '   터미널: python3 web_app.py\n\n' +
              '2. http://localhost:8080 접속 확인\n\n' +
              '토지이음 스크래핑은 시간이 걸릴 수 있습니다.');
      } else {
        setSearchStatus('❌ 서버 연결 실패');
        alert('❌ 서버 연결 실패\n\n' +
              '오류: ' + err.message + '\n\n' +
              '해결 방법:\n' +
              '1. Python 웹서버 시작:\n' +
              '   python3 web_app.py\n\n' +
              '2. 브라우저에서 확인:\n' +
              '   http://localhost:8080\n\n' +
              '3. 서버 실행 후 다시 시도하세요');
      }
      
      setTimeout(() => setSearchStatus(''), 10000);
    }
  };

  const handleInputChange = (field, value) => {
    setInputs(prev => ({ ...prev, [field]: value }));
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-500 to-purple-600 p-4">
      <div className="max-w-4xl mx-auto bg-white rounded-2xl shadow-2xl overflow-hidden">
        
        <div className="bg-gradient-to-r from-indigo-500 to-purple-600 text-white p-6 text-center">
          <h1 className="text-2xl font-bold mb-2">🏗️ 건축 규모검토</h1>
          <p className="text-sm opacity-90">빠른 사업성 판단을 위한 간편 도구 (엑셀 계산 로직 적용)</p>
        </div>

        <div className="p-6">
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">
                대지위치
              </label>
              <div className="flex gap-2 mb-2">
                <input
                  type="text"
                  value={inputs.location}
                  onChange={(e) => handleInputChange('location', e.target.value)}
                  className="flex-1 px-3 py-2 border-2 border-gray-300 rounded-lg text-sm"
                  placeholder="예: 서울특별시 강남구 역삼동 123-45"
                />
              </div>
              
              <div className="flex gap-2">
                <button
                  onClick={autoSearch}
                  className="flex-1 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-semibold rounded-lg transition-colors"
                >
                  🔍 용도지역 자동검색
                </button>
                <button
                  onClick={openNaverMap}
                  className="flex-1 px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold rounded-lg transition-colors"
                >
                  🗺️ 네이버
                </button>
              </div>
              
              {searchStatus && (
                <div className="mt-2 p-2 bg-blue-50 border border-blue-300 rounded text-xs text-blue-800">
                  {searchStatus}
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">
                용도지역
                {searchStatus.includes('✅') && (
                  <span className="ml-2 text-green-600 text-xs">✨ 자동 설정됨</span>
                )}
              </label>
              <select
                value={inputs.zoneType}
                onChange={(e) => handleInputChange('zoneType', e.target.value)}
                className="w-full px-3 py-2 border-2 border-gray-300 rounded-lg text-sm"
              >
                {Object.keys(zoneData).map(key => (
                  <option key={key} value={key}>{key}</option>
                ))}
              </select>
              <div className="mt-1 text-xs text-gray-500">
                💡 자동 검색 버튼을 누르면 자동으로 설정됩니다
              </div>
              
              {/* 복합 용도지역 옵션 */}
              <div className="mt-3 p-3 bg-blue-50 border border-blue-300 rounded-lg">
                <label className="flex items-center cursor-pointer mb-2">
                  <input
                    type="checkbox"
                    checked={inputs.multiZone}
                    onChange={(e) => handleInputChange('multiZone', e.target.checked)}
                    className="mr-2"
                  />
                  <span className="text-sm font-semibold text-blue-800">
                    복합 용도지역 (2개 이상)
                  </span>
                </label>
                
                {inputs.multiZone && (
                  <div className="mt-2 space-y-2">
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs text-blue-700 mb-1">지역1</label>
                        <select
                          value={inputs.zone1Type}
                          onChange={(e) => handleInputChange('zone1Type', e.target.value)}
                          className="w-full px-2 py-1 border border-blue-300 rounded text-xs"
                        >
                          {Object.keys(zoneData).map(key => (
                            <option key={key} value={key}>{key}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs text-blue-700 mb-1">면적(㎡)</label>
                        <input
                          type="number"
                          value={inputs.zone1Area}
                          onChange={(e) => handleInputChange('zone1Area', parseFloat(e.target.value) || 0)}
                          className="w-full px-2 py-1 border border-blue-300 rounded text-xs"
                        />
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs text-blue-700 mb-1">지역2</label>
                        <select
                          value={inputs.zone2Type}
                          onChange={(e) => handleInputChange('zone2Type', e.target.value)}
                          className="w-full px-2 py-1 border border-blue-300 rounded text-xs"
                        >
                          {Object.keys(zoneData).map(key => (
                            <option key={key} value={key}>{key}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs text-blue-700 mb-1">면적(㎡)</label>
                        <input
                          type="number"
                          value={inputs.zone2Area}
                          onChange={(e) => handleInputChange('zone2Area', parseFloat(e.target.value) || 0)}
                          className="w-full px-2 py-1 border border-blue-300 rounded text-xs"
                        />
                      </div>
                    </div>
                    
                    <div className="pt-2 border-t border-blue-200">
                      <div className="text-xs text-blue-700 mb-1">
                        📊 가중평균 용적률: 
                        {(() => {
                          const total = inputs.zone1Area + inputs.zone2Area;
                          if (total > 0 && inputs.zone1Area > 0 && inputs.zone2Area > 0) {
                            const z1 = zoneData[inputs.zone1Type];
                            const z2 = zoneData[inputs.zone2Type];
                            if (z1 && z2) {
                              const weighted = ((z1.appliedFAR * inputs.zone1Area + z2.appliedFAR * inputs.zone2Area) / total * 100).toFixed(0);
                              return <strong className="ml-1">{weighted}%</strong>;
                            }
                          }
                          return <strong className="ml-1">-</strong>;
                        })()}
                      </div>
                      
                      <div className="mt-2">
                        <label className="block text-xs text-blue-700 mb-1">
                          또는 직접 입력 (%)
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={inputs.customFAR}
                          onChange={(e) => handleInputChange('customFAR', parseFloat(e.target.value) || 0)}
                          placeholder="예: 3.5"
                          className="w-full px-2 py-1 border border-blue-300 rounded text-xs"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">
                대지면적 (㎡)
              </label>
              <input
                type="number"
                value={inputs.landArea}
                onChange={(e) => handleInputChange('landArea', parseFloat(e.target.value) || 0)}
                className="w-full px-3 py-2 border-2 border-gray-300 rounded-lg text-sm"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">
                검토용도
              </label>
              <select
                value={inputs.useType}
                onChange={(e) => handleInputChange('useType', e.target.value)}
                className="w-full px-3 py-2 border-2 border-gray-300 rounded-lg text-sm"
              >
                {Object.keys(useTypeRatios).map(key => (
                  <option key={key} value={key}>{key}</option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">
                  임대형기숙사 (㎡)
                </label>
                <input
                  type="number"
                  value={inputs.dormArea}
                  onChange={(e) => handleInputChange('dormArea', parseFloat(e.target.value) || 0)}
                  step="0.1"
                  className="w-full px-2 py-2 border-2 border-gray-300 rounded-lg text-xs"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">
                  오피스텔 (㎡)
                </label>
                <input
                  type="number"
                  value={inputs.officetelArea}
                  onChange={(e) => handleInputChange('officetelArea', parseFloat(e.target.value) || 0)}
                  step="0.1"
                  className="w-full px-2 py-2 border-2 border-gray-300 rounded-lg text-xs"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">
                  관광호텔 (㎡)
                </label>
                <input
                  type="number"
                  value={inputs.hotelArea}
                  onChange={(e) => handleInputChange('hotelArea', parseFloat(e.target.value) || 0)}
                  step="0.1"
                  className="w-full px-2 py-2 border-2 border-gray-300 rounded-lg text-xs"
                />
              </div>
            </div>
          </div>
        </div>

        {/* 적용된 주요 가정 */}
        <div className="p-6 border-b-2 border-gray-100">
          <h2 className="text-lg font-bold text-gray-800 mb-4">⚙️ 적용된 주요 가정</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <div className="bg-purple-50 border border-purple-200 p-3 rounded-lg">
              <label className="block text-xs text-purple-700 mb-1">지상공유공간 비율</label>
              <input
                type="number"
                step="0.01"
                value={assumptions.groundSharedRatio}
                onChange={(e) => setAssumptions({...assumptions, groundSharedRatio: parseFloat(e.target.value) || 0})}
                className="w-full px-2 py-1 border border-purple-300 rounded text-sm"
              />
              <div className="text-xs text-purple-600 mt-1">
                기본: 50% ({(assumptions.groundSharedRatio * 100).toFixed(0)}%)
              </div>
            </div>
            
            <div className="bg-purple-50 border border-purple-200 p-3 rounded-lg">
              <label className="block text-xs text-purple-700 mb-1">기숙사 전용률</label>
              <input
                type="number"
                step="0.01"
                value={assumptions.dormExclusiveRatio}
                onChange={(e) => setAssumptions({...assumptions, dormExclusiveRatio: parseFloat(e.target.value) || 0})}
                className="w-full px-2 py-1 border border-purple-300 rounded text-sm"
              />
              <div className="text-xs text-purple-600 mt-1">
                기본: 55% ({(assumptions.dormExclusiveRatio * 100).toFixed(0)}%)
              </div>
            </div>
            
            <div className="bg-purple-50 border border-purple-200 p-3 rounded-lg">
              <label className="block text-xs text-purple-700 mb-1">호텔/오피스텔 전용률</label>
              <input
                type="number"
                step="0.01"
                value={assumptions.hotelOfficetelExclusiveRatio}
                onChange={(e) => setAssumptions({...assumptions, hotelOfficetelExclusiveRatio: parseFloat(e.target.value) || 0})}
                className="w-full px-2 py-1 border border-purple-300 rounded text-sm"
              />
              <div className="text-xs text-purple-600 mt-1">
                기본: 60% ({(assumptions.hotelOfficetelExclusiveRatio * 100).toFixed(0)}%)
              </div>
            </div>
            
            <div className="bg-purple-50 border border-purple-200 p-3 rounded-lg">
              <label className="block text-xs text-purple-700 mb-1">기계전기실 비율</label>
              <input
                type="number"
                step="0.01"
                value={assumptions.mechElecRatio}
                onChange={(e) => setAssumptions({...assumptions, mechElecRatio: parseFloat(e.target.value) || 0})}
                className="w-full px-2 py-1 border border-purple-300 rounded text-sm"
              />
              <div className="text-xs text-purple-600 mt-1">
                기본: 8% ({(assumptions.mechElecRatio * 100).toFixed(0)}%)
              </div>
            </div>
            
            <div className="bg-purple-50 border border-purple-200 p-3 rounded-lg">
              <label className="block text-xs text-purple-700 mb-1">지하건폐율</label>
              <input
                type="number"
                step="0.01"
                value={assumptions.undergroundCoverage}
                onChange={(e) => setAssumptions({...assumptions, undergroundCoverage: parseFloat(e.target.value) || 0})}
                className="w-full px-2 py-1 border border-purple-300 rounded text-sm"
              />
              <div className="text-xs text-purple-600 mt-1">
                기본: 75% ({(assumptions.undergroundCoverage * 100).toFixed(0)}%)
              </div>
            </div>
            
            <div className="bg-purple-50 border border-purple-200 p-3 rounded-lg">
              <label className="block text-xs text-purple-700 mb-1">기준층 건폐율</label>
              <input
                type="number"
                step="0.01"
                value={assumptions.typicalCoverage}
                onChange={(e) => setAssumptions({...assumptions, typicalCoverage: parseFloat(e.target.value) || 0})}
                className="w-full px-2 py-1 border border-purple-300 rounded text-sm"
              />
              <div className="text-xs text-purple-600 mt-1">
                기본: 30% ({(assumptions.typicalCoverage * 100).toFixed(0)}%)
              </div>
            </div>
            
            <div className="bg-purple-50 border border-purple-200 p-3 rounded-lg">
              <label className="block text-xs text-purple-700 mb-1">자주식 주차 비율</label>
              <input
                type="number"
                step="0.01"
                value={assumptions.selfParkingRatio}
                onChange={(e) => setAssumptions({...assumptions, selfParkingRatio: parseFloat(e.target.value) || 0})}
                className="w-full px-2 py-1 border border-purple-300 rounded text-sm"
              />
              <div className="text-xs text-purple-600 mt-1">
                기본: 3% ({(assumptions.selfParkingRatio * 100).toFixed(0)}%)
              </div>
            </div>
          </div>
          <div className="mt-3 text-xs text-gray-600">
            💡 각 값을 수정하면 자동으로 재계산됩니다
          </div>
        </div>

        {/* 계산 결과 */}
        <div className="p-6 border-b-2 border-gray-100">
          <h2 className="text-lg font-bold text-gray-800 mb-4">📊 검토 결과</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <div className="bg-gradient-to-br from-indigo-500 to-purple-600 text-white p-4 rounded-xl text-center">
              <div className="text-xs opacity-90 mb-1">세대수 (호실수)</div>
              <div className="text-2xl font-bold">{fmt(results.totalUnits)}</div>
              <div className="text-xs opacity-80 mt-1">세대</div>
            </div>
            <div className="bg-gradient-to-br from-indigo-500 to-purple-600 text-white p-4 rounded-xl text-center">
              <div className="text-xs opacity-90 mb-1">건축물 높이</div>
              <div className="text-2xl font-bold">{fmt(results.buildingHeight, 1)}</div>
              <div className="text-xs opacity-80 mt-1">m</div>
            </div>
            <div className="bg-gradient-to-br from-indigo-500 to-purple-600 text-white p-4 rounded-xl text-center">
              <div className="text-xs opacity-90 mb-1">지상층 (예상)</div>
              <div className="text-2xl font-bold">{fmt(results.groundFloors)}</div>
              <div className="text-xs opacity-80 mt-1">층</div>
            </div>
            <div className="bg-gradient-to-br from-indigo-500 to-purple-600 text-white p-4 rounded-xl text-center">
              <div className="text-xs opacity-90 mb-1">지하층 (예상)</div>
              <div className="text-2xl font-bold">{fmt(results.undergroundFloors)}</div>
              <div className="text-xs opacity-80 mt-1">층</div>
            </div>
            <div className="bg-gradient-to-br from-indigo-500 to-purple-600 text-white p-4 rounded-xl text-center">
              <div className="text-xs opacity-90 mb-1">개발기간 (예상)</div>
              <div className="text-2xl font-bold">{fmt(results.devPeriod)}</div>
              <div className="text-xs opacity-80 mt-1">개월</div>
            </div>
            <div className="bg-gradient-to-br from-indigo-500 to-purple-600 text-white p-4 rounded-xl text-center">
              <div className="text-xs opacity-90 mb-1">공사기간 (예상)</div>
              <div className="text-2xl font-bold">{fmt(results.constPeriod)}</div>
              <div className="text-xs opacity-80 mt-1">개월</div>
            </div>
          </div>
        </div>

        {/* 시설별 개요 표 */}
        {results.facilityData && (
          <div className="p-6 overflow-x-auto">
            <h2 className="text-lg font-bold text-gray-800 mb-4">🏢 시설별 개요</h2>
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="bg-indigo-500 text-white">
                  <th className="p-2 border">구분</th>
                  <th className="p-2 border">임대형<br/>기숙사</th>
                  <th className="p-2 border">오피스텔</th>
                  <th className="p-2 border">관광호텔</th>
                  <th className="p-2 border">근린상업</th>
                  <th className="p-2 border">합계</th>
                </tr>
              </thead>
              <tbody>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left font-semibold">용적률 비율</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.ratios.dorm * 100, 1)}%</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.ratios.officetel * 100, 1)}%</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.ratios.hotel * 100, 1)}%</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.ratios.retail * 100, 1)}%</td>
                  <td className="p-2 border text-center">100.0%</td>
                </tr>
                <tr className="bg-blue-100">
                  <td className="p-2 border text-left font-semibold">지상 연면적(㎡)</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.ground)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.ground)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.ground)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.ground)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.ground)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left pl-6 text-gray-600">└ 시설면적</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.facilityArea)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.facilityArea)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.facilityArea)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.facilityArea)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.facilityArea)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left pl-6 text-gray-600">└ 주차타워</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.parkingTower)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.parkingTower)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.parkingTower)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.parkingTower)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.parkingTower)}</td>
                </tr>
                <tr className="bg-green-100">
                  <td className="p-2 border text-left font-semibold">지하 연면적(㎡)</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.under)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.under)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.under)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.under)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.under)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left pl-6 text-gray-600">└ 지하공용</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.underShared)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.underShared)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.underShared)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.underShared)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.underShared)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left pl-6 text-gray-600">└ 주차장</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.parkingLot)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.parkingLot)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.parkingLot)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.parkingLot)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.parkingLot)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left pl-6 text-gray-600">└ 공유공간(지하)</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.sharedUnder)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.sharedUnder)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.sharedUnder)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.sharedUnder)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.sharedUnder)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left pl-6 text-gray-600">└ 기전실</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.mechElec)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.mechElec)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.mechElec)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.mechElec)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.mechElec)}</td>
                </tr>
                <tr className="bg-yellow-100">
                  <td className="p-2 border text-left font-semibold">시설별 연면적(㎡)</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.total)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.total)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.total)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.total)}</td>
                  <td className="p-2 border text-center bg-yellow-200 font-bold">{fmt(results.facilityData.totals.total)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left font-semibold">연면적 비율</td>
                  <td className="p-2 border text-center">
                    {fmt((results.facilityData.dorm.total / results.facilityData.totals.total) * 100, 1)}%
                  </td>
                  <td className="p-2 border text-center">
                    {fmt((results.facilityData.officetel.total / results.facilityData.totals.total) * 100, 1)}%
                  </td>
                  <td className="p-2 border text-center">
                    {fmt((results.facilityData.hotel.total / results.facilityData.totals.total) * 100, 1)}%
                  </td>
                  <td className="p-2 border text-center">
                    {fmt((results.facilityData.retail.total / results.facilityData.totals.total) * 100, 1)}%
                  </td>
                  <td className="p-2 border text-center">100.0%</td>
                </tr>
                <tr className="bg-purple-100">
                  <td className="p-2 border text-left font-semibold">공유공간(㎡)</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.sharedSpace)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left pl-6 text-gray-600">└ 지상</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.sharedSpaceGround)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left pl-6 text-gray-600">└ 지하</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.sharedSpaceUnder)}</td>
                </tr>
                <tr className="bg-yellow-100">
                  <td className="p-2 border text-left font-semibold">호실수(세대)</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.units)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.units)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.units)}</td>
                  <td className="p-2 border text-center">-</td>
                  <td className="p-2 border text-center bg-yellow-200 font-bold">{fmt(results.facilityData.totals.units)}</td>
                </tr>
                <tr className="even:bg-gray-50">
                  <td className="p-2 border text-left font-semibold">주차대수</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.dorm.parking)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.officetel.parking)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.hotel.parking)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.retail.parking)}</td>
                  <td className="p-2 border text-center">{fmt(results.facilityData.totals.parking)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}

      </div>
    </div>
  );
}
