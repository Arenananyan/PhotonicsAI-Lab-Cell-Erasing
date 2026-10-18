'use strict';
window.LabUI = (() => {
  const pairs = {
    'Open Photonics AI assistant':'Բացել Photonics AI օգնականը',
    'Photonics assistant':'Photonics օգնական', 'Close assistant':'Փակել օգնականը',
    'Ask about your lab or describe a task. Results appear in the conversation.':'Հարցրու լաբորատորիայի մասին կամ նկարագրիր առաջադրանքը։ Արդյունքները կհայտնվեն զրույցում։',
    'Ask about your lab or describe a task…':'Հարցրու լաբորատորիայի մասին կամ նկարագրիր առաջադրանքը…',
    'Question or task':'Հարց կամ առաջադրանք', 'Send to lab':'Ուղարկել լաբորատորիային',
    'Inspect cells':'Դիտարկել բջիջները', 'Printer status':'Պրինտերի վիճակը',
    'Clean largest blue':'Մաքրել ամենամեծ կապույտը',
    'Movement still requires your path approval.':'Շարժման համար անհրաժեշտ է ճանապարհի քո հաստատումը։',
    'Finish or cancel the current task before sending another.':'Ավարտիր կամ չեղարկիր ընթացիկ առաջադրանքը՝ նորը ուղարկելուց առաջ։',
    'Demo mode: simulated lab data. Connect AI for free-form requests.':'Դեմո ռեժիմ․ լաբորատորիայի տվյալները սիմուլյացիոն են։ Ազատ հարցումների համար միացրու ԱԻ։',
    'Questions are read-only. Review paths before any movement.':'Հարցերը շարժում չեն կատարում։ Ստուգիր ճանապարհը ցանկացած շարժումից առաջ։',
    'Make the Photonics AI mascot hop':'Թռցնել Photonics AI թալիսմանին',
    'Pause mascot animation':'Դադարեցնել թալիսմանի շարժումը',
    'Resume mascot animation':'Վերսկսել թալիսմանի շարժումը',
    'Mascot animation follows your reduced motion setting':'Թալիսմանի շարժումն անջատված է ըստ շարժման նվազեցման կարգավորման',
    'Pause':'Դադար', 'Resume':'Շարունակել',
    'New command':'Նոր հրահանգ', 'New chat':'Նոր չատ', 'YOUR WORKSPACE':'ՔՈ ՉԱՏԵՐԸ',
    'Dark mode':'Մուգ ռեժիմ', 'Light mode':'Բաց ռեժիմ',
    'Switch to dark mode':'Միացնել մուգ ռեժիմը', 'Switch to light mode':'Միացնել բաց ռեժիմը',
    'Delete chat':'Ջնջել չատը', 'Delete this chat?':'Ջնջե՞լ այս չատը։', 'Keep chat':'Պահպանել չատը',
    'This removes the conversation from this browser. Saved experiment records are kept.':'Չատը կջնջվի այս բրաուզերի պատմությունից։ Փորձերի պահպանված գրառումները կմնան։',
    'Could not delete saved chat. Please try again.':'Չհաջողվեց ջնջել պահպանված չատը։ Նորից փորձիր։',
    'Board observation':'Տախտակի դիտարկում', 'CAPTURED FRAME':'ՊԱՀՊԱՆՎԱԾ ԿԱԴՐ',
    'Loading captured image…':'Բեռնվում է պահպանված պատկերը…', 'Board image unavailable':'Տախտակի նկարը հասանելի չէ',
    'Cell image unavailable':'Բջջի նկարը հասանելի չէ', 'Cell':'Բջիջ',
    'Numbers match the board image. Cell pictures use the same captured frame.':'Համարները համապատասխանում են տախտակի պատկերին։ Բջիջների նկարները նույն կադրից են։',
    'Preparing the request…':'Մշակում ենք հրահանգը…', 'I’m checking your request.':'Ստուգում եմ քո հրահանգը։',
    'A little space for your next discovery.':'Այստեղ կպահվեն քո հրահանգները։',
    'Your commands will appear here.':'Կարող ես վերադառնալ նախորդ արդյունքներին։',
    'Yerevan State University':'Երևանի պետական համալսարան',
    'Light. Intelligence. Discovery.':'Լույս։ Բանականություն։ Բացահայտում։',
    'WORKSPACE':'ԱՇԽԱՏԱՏԱՐԱԾՔ', 'Connecting':'Միանում է…',
    "Let's find that":'Եկ բացահայտենք', 'green cell.':'բջիջները։',
    'From a simple instruction to a precise action.':'Պարզ հրահանգից՝ ճշգրիտ գործողություն։',
    'Your lab, in conversation.':'Խոսիր քո լաբորատորիայի հետ։',
    'Find & clean':'Գտնել և մաքրել', 'Clean the largest green cell':'Մաքրել ամենամեծ կանաչ բջիջը',
    'Take a closer look':'Դիտարկել բջիջները', 'Inspect the cells on the bed':'Ստանալ բջիջների չափերն ու ցանկը',
    'Back to the start':'Վերադառնալ տուն', 'Plan a return to home':'Պատրաստել տուն գնալու ուղին',
    'Computer vision meets precise motion':'Ճանաչում և ճշգրիտ շարժում',
    'Describe. Discover. Do.':'Հրահանգիր։ Դիտարկիր։ Գործիր։',
    'Powered by vision. Guided by you.':'Ճանաչում՝ համակարգից։ Կառավարում՝ քեզնից։',
    'Review every path before execution.':'Կատարելուց առաջ ստուգիր ճանապարհը։',
    'Ask your lab to do something…':'Գրիր հրահանգ կամ հարց…', 'Reply to your lab…':'Գրիր պատասխանդ…',
    'Your answer continues this command':'Պատասխանդ կշարունակի այս առաջադրանքը',
    'Following your current command':'Ընթացիկ առաջադրանքը կատարվում է',
    'Send command':'Ուղարկել հրահանգը', 'Your command or answer':'Քո հրահանգը կամ պատասխանը',
    'Scanner ↗':'Ճանաչող ↗', 'Camera ↗':'Կամերա ↗', 'Open command history':'Բացել հրամանների պատմությունը',
    'Close sidebar':'Փակել կողային վահանակը', 'Target inspection':'Թիրախի դիտարկում',
    'Zoom out':'Փոքրացնել', 'Zoom in':'Մեծացնել', 'Reset':'Վերականգնել',
    'Close image viewer':'Փակել պատկերը', 'Scroll or pinch to zoom · drag to pan · Esc to close':'Ոլորիր՝ մեծացնելու, քաշիր՝ տեղափոխելու համար · Esc՝ փակել',
    'Emergency stop':'Արտակարգ կանգ', 'Emergency shutdown?':'Արտակարգ կանգ պահանջե՞լ։',
    'This requests a printer shutdown. Manual recovery may be required.':'Սա կկանգնեցնի պրինտերը։ Հետո կարող է պահանջվել ձեռքով վերականգնում։',
    'Keep running':'Շարունակել աշխատանքը', 'Request shutdown':'Պահանջել կանգ',
    'Stop simulation':'Կանգնեցնել սիմուլյացիան', 'Reset simulation':'Վերականգնել սիմուլյացիան',
    'Simulated printer reset.':'Սիմուլյացիոն պրինտերը վերականգնված է։',
    'Emergency shutdown requested. Check the printer.':'Արտակարգ կանգը պահանջված է։ Ստուգիր պրինտերը։',
    'Synthetic simulation':'Սինթետիկ սիմուլյացիա', 'Simulated printer':'Սիմուլյացիոն պրինտեր',
    'Real printer · motion enabled':'Իրական պրինտեր · շարժումը միացված է',
    'Real printer · preview only':'Իրական պրինտեր · միայն նախադիտում', 'Disconnected':'Կապ չկա',
    'Activity trace':'Ընթացք', 'Scanning bed & reasoning…':'Ստուգում և պլանավորում…',
    'Executing the approved path…':'Կատարվում է հաստատված ուղին…',
    'A little more information will help me continue.':'Շարունակելու համար պատասխանիր ստորև նշված հարցին։',
    'The path is ready. Review the target and complete route below before approving.':'Ճանապարհը պատրաստ է։ Հաստատելուց առաջ ստուգիր թիրախն ու ամբողջ ուղին։',
    'Stop requested. The current queued path may finish; no next path will begin.':'Դադարը պահանջված է։ Ընթացիկ ուղին կավարտվի, հաջորդը չի սկսվի։',
    'Following the approved path. I’ll report the result when the tools return.':'Կատարվում է հաստատված ուղին։ Արդյունքը կցուցադրվի ավարտից հետո։',
    'I’m checking the request, the camera, and the available path.':'Ստուգում եմ հրահանգը, կամերան և ճանապարհը։',
    'The command could not finish. No automatic movement retry was made.':'Առաջադրանքը չավարտվեց։ Շարժման ավտոմատ կրկնում չի կատարվել։',
    'This command was cancelled.':'Առաջադրանքը չեղարկված է։', 'The task has stopped.':'Առաջադրանքը կանգնեցված է։',
    'Target acquired':'Թիրախը գտնված է', 'Computer vision':'Բջիջների ճանաչում',
    'ANNOTATED FRAME':'ՖԻՔՍՎԱԾ ԿԱԴՐ', 'Locating your target':'Փնտրում ենք թիրախը',
    'Mapping the field of view…':'Ստուգում ենք պատկերը…', 'Target image unavailable':'Թիրախի պատկերը հասանելի չէ',
    'Review the home path':'Ստուգիր տուն գնալու ուղին', 'Review the cleaning path':'Ստուգիր մաքրման ուղին',
    'Review the movement path':'Ստուգիր շարժման ուղին', 'Displayed path':'Ցուցադրված ուղին',
    'APPROVAL REQUIRED':'ՍՊԱՍՈՒՄ Է ՀԱՍՏԱՏՄԱՆ', 'RECORDED PLAN':'ԳՐԱՆՑՎԱԾ ՊԼԱՆ',
    'View complete path':'Դիտել ամբողջ ճանապարհը', 'waypoints':'կետ', 'Step':'Քայլ',
    'Already at the initial position; there is no travel step.':'Գլխիկն արդեն սկզբնական դիրքում է․ տեղափոխման քայլ չկա։',
    'Approve & execute':'Հաստատել և կատարել', 'Cancel command':'Չեղարկել առաջադրանքը',
    'Only the displayed path is covered by its approval. A new path requires a new confirmation.':'Հաստատված է միայն ցուցադրված ուղին։ Նոր ուղին պահանջում է նոր հաստատում։',
    'Approve within 110 seconds of path preparation. The task limit is 30 minutes. Home is a configured position, not a G28 homing command.':'Հաստատիր պլանը պատրաստելուց մինչև 110 վրկ անց։ Առաջադրանքի սահմանը՝ 30 րոպե։ «Տունը» նշված դիրք է, ոչ G28 հրաման։',
    'I reviewed the complete path, motion limits, and clearance of the entire tool footprint':'Վերանայել եմ ամբողջ ուղին, շարժման սահմանները և գործիքի անցման ազատ լինելը',
    'including Z 14.5 mm and the R 10 mm circle':'ներառյալ Z=14.5 մմ և R=10 մմ շրջանը',
    'Toolhead execution':'Գլխիկի շարժում', 'PLAN VISUALIZATION':'ՃԱՆԱՊԱՐՀԻ ՍԽԵՄԱ',
    'Home / path check':'Տուն / ուղու ստուգում', 'Before capture':'Պատկեր՝ մինչև',
    'Toolhead action':'Գլխիկի շարժում', 'After capture':'Պատկեր՝ հետո',
    'Schematic · no live telemetry':'Սխեմա · ընթացիկ դիրքի չափում չէ',
    'Visual assessment':'Տեսողական գնահատում', 'BEFORE':'ՄԻՆՉԵՎ', 'AFTER':'ՀԵՏՈ',
    'Drag to compare':'Քաշիր՝ համեմատելու համար', 'Enlarge before':'Մեծացնել՝ մինչև',
    'Enlarge after':'Մեծացնել՝ հետո', 'Colored residue':'Գունավոր մնացորդ',
    'Evidence image unavailable':'Արդյունքի պատկերը հասանելի չէ',
    'Stop after current path':'Դադարեցնել ընթացիկ ուղուց հետո',
    'Cells by measured area':'Բջիջներն ըստ մակերեսի', 'Agent suggestions':'Ագենտի առաջարկները',
    'Selecting a suggestion only fills the command. Review the plan and approve movement separately.':'Առաջարկն ընտրելը միայն լրացնում է հրահանգը։ Ճանապարհն ու շարժումը կհաստատես առանձին։',
    'Target queue':'Թիրախների հերթ', 'Current':'Ընթացիկ', 'Pending':'Սպասում է',
    'Condition':'Պայման', 'Condition met':'Պայմանը կատարվում է', 'Condition not met':'Պայմանը չի կատարվում',
    'blue_count':'Կապույտների քանակ', 'green_count':'Կանաչների քանակ', 'total_count':'Բոլոր բջիջների քանակ',
    'blue_area_mm2':'Կապույտների ընդհանուր մակերես', 'green_area_mm2':'Կանաչների ընդհանուր մակերես',
    'blue':'Կապույտ', 'green':'Կանաչ', 'largest':'Ամենամեծը', 'smallest':'Ամենափոքրը', 'all':'Բոլորը', 'nearest':'Ամենամոտը',
    'clean':'Մաքրված', 'residue':'Մնացորդ կա', 'uncertain':'Անորոշ', 'skipped':'Բաց թողնված',
    'completed':'Ավարտված է', 'failed':'Չհաջողվեց', 'cancelled':'Չեղարկված է',
    'observed':'Դիտարկված է', 'stopped':'Կանգնեցված է', 'awaiting_confirmation':'Սպասում է հաստատմանը',
    'awaiting_answer':'Սպասում է պատասխանին', 'preparing':'Պատրաստվում է', 'executing':'Կատարվում է',
    'Finish or cancel the current command before opening another.':'Նոր հրահանգից առաջ ավարտիր կամ չեղարկիր ընթացիկը։',
    'This run is no longer available on the server. Its saved conversation is shown; start a new command to continue.':'Այս փորձն այլևս հասանելի չէ սերվերում։ Պատմությունը պահպանված է․ շարունակելու համար պատրաստիր նոր առաջադրանք։'
  };
  let language='hy';
  try { language=localStorage.getItem('labLanguage')==='en'?'en':'hy'; } catch {}
  const names={blue_count:'Blue cell count',green_count:'Green cell count',total_count:'Total cell count',
    blue_area_mm2:'Total blue area',green_area_mm2:'Total green area',blue:'Blue',green:'Green',
    largest:'Largest',smallest:'Smallest',all:'All',nearest:'Nearest'};
  const t=text=>language==='hy'?(pairs[text]||text):(names[text]||text);
  function translate(root) {
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    let node;
    while((node=walker.nextNode())) {
      if(node.parentElement.closest('[data-content],script,style'))continue;
      const key=node.textContent.trim();
      if(pairs[key])node.textContent=node.textContent.replace(key,t(key));
    }
  }
  const staticText=[],staticAttributes=[];
  function capture() {
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    let node;
    while((node=walker.nextNode())) {
      if (node.parentElement.closest('script,style')) continue;
      const original=node.textContent, key=original.trim();
      if(pairs[key]) staticText.push({node,original,key});
    }
    for(const element of document.querySelectorAll('[aria-label],[placeholder],[title]')) {
      for(const name of ['aria-label','placeholder','title']) {
        const value=element.getAttribute(name);
        if(pairs[value]) staticAttributes.push({element,name,value});
      }
    }
  }
  function apply() {
    document.documentElement.lang=language;
    for(const {node,original,key} of staticText) if(node.isConnected)node.textContent=original.replace(key,t(key));
    for(const {element,name,value} of staticAttributes)element.setAttribute(name,t(value));
    document.getElementById('language').textContent=language==='hy'?'English':'Հայերեն';
  }
  function toggle() {
    language=language==='hy'?'en':'hy';
    try { localStorage.setItem('labLanguage',language); } catch {}
    apply();
  }
  return {t,capture,apply,toggle,translate,get language(){return language;}};
})();
